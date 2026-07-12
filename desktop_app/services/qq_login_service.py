from PySide6.QtCore import QObject, Signal, QTimer
from desktop_app.services.napcat_webui_service import (
    NapCatWebUIService,
    WebUIRequestTask,
)
from desktop_app.services.secret_service import SecretService
import os

class QQLoginService(QObject):
    login_success = Signal()
    login_failed = Signal(str)
    qrcode_ready = Signal(str, str) # type ('url' or 'file'), data
    status_updated = Signal(str)
    logout_stop_finished = Signal(bool, str)
    _logout_response_received = Signal(object)
    _logout_error_received = Signal(str)
    
    def __init__(self, napcat_service, webui_service: NapCatWebUIService):
        super().__init__()
        self.napcat_service = napcat_service
        self.webui_service = webui_service
        
        self.poll_timer = QTimer()
        self.poll_timer.setInterval(1500)
        self.poll_timer.timeout.connect(self._poll_status)
        
        self.webui_service.login_status_result.connect(self._handle_status_result)
        self.webui_service.login_status_error.connect(self._handle_status_error)
        self.webui_service.qrcode_result.connect(self._handle_qrcode_result)
        self.webui_service.qrcode_error.connect(self._handle_qrcode_error)
        self.webui_service.quick_login_clear_result.connect(
            self._handle_quick_login_clear_result
        )
        self.webui_service.quick_login_clear_error.connect(
            self._handle_quick_login_clear_error
        )
        
        # Listen to napcat log fallback
        self.napcat_service.qrcode_url_detected.connect(self._handle_fallback_url)
        self.napcat_service.qrcode_file_detected.connect(self._handle_fallback_file)
        self.napcat_service.webui_detected.connect(self._handle_webui_detected)
        self.napcat_service.process_failed.connect(self._handle_process_failed)
        self.napcat_service.stop_completed.connect(
            self._handle_napcat_stop_completed
        )
        self._logout_response_received.connect(self._handle_logout_response)
        self._logout_error_received.connect(self._handle_logout_error)
        
        self._waiting_for_webui = False
        self._fallback_qr_url = None
        self._fallback_qr_file = None
        self._cached_webui_url = ""
        self._cached_webui_token = ""
        
        self._is_polling = False
        self._current_request_in_flight = False
        self._logout_stop_in_progress = False
        self._pending_quick_login_cleared = False
        self._waiting_for_napcat_stop = False

    def start_login_flow(self):
        self.status_updated.emit("正在启动 NapCat 和获取状态...")
        self._is_polling = True
        self._setup_and_authenticate_webui()
        self.poll_timer.start()
        
        # If we already have a cached QR code, emit it immediately
        if self._fallback_qr_url:
            self.qrcode_ready.emit("url", self._fallback_qr_url)
            self.status_updated.emit("等待扫码 (缓存)")
        elif self._fallback_qr_file:
            self.qrcode_ready.emit("file", self._fallback_qr_file)
            self.status_updated.emit("等待扫码 (缓存)")

    def cancel_login(self):
        self.poll_timer.stop()
        self._is_polling = False
        self.status_updated.emit("登录已取消")
        
    def refresh_qr(self):
        if self._is_polling:
            self.status_updated.emit("正在刷新二维码...")
            self.webui_service.refresh_qrcode()

    def logout_and_stop(self):
        if self._logout_stop_in_progress:
            return False

        self.cancel_login()
        self._logout_stop_in_progress = True
        self._pending_quick_login_cleared = False
        self._waiting_for_napcat_stop = False
        self.status_updated.emit("正在退出 QQ 并停止 NapCat...")

        if self.webui_service.base_url:
            self.webui_service.clear_quick_login()
        else:
            QTimer.singleShot(
                0,
                lambda: self._handle_quick_login_clear_error(
                    "WebUI 地址尚未获取"
                ),
            )
        return True

    def _handle_quick_login_clear_result(self):
        if not self._logout_stop_in_progress:
            return
        self._pending_quick_login_cleared = True
        self._request_bot_exit_and_stop_napcat()

    def _handle_quick_login_clear_error(self, _error):
        if not self._logout_stop_in_progress:
            return
        self._pending_quick_login_cleared = False
        self._request_bot_exit_and_stop_napcat()

    def _request_bot_exit_and_stop_napcat(self):
        self._submit_best_effort_bot_exit()
        if self.napcat_service.stop():
            self._waiting_for_napcat_stop = True
            return
        self._emit_logout_stop_result(stopped_internal=False)

    def _submit_best_effort_bot_exit(self):

        base_url = self.napcat_service.settings_service.get(
            "ONEBOT_API_URL", "http://127.0.0.1:3000"
        ).rstrip("/")
        headers = {"Content-Type": "application/json"}
        token = SecretService.get_secret("ONEBOT_ACCESS_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        task = WebUIRequestTask(
            url=f"{base_url}/bot_exit",
            method="POST",
            headers=headers,
            json_data={},
            timeout=5,
            callback=self._logout_response_received.emit,
            error_callback=self._logout_error_received.emit,
        )
        self.webui_service.thread_pool.start(task)

    def _handle_logout_response(self, response):
        self.napcat_service.log_emitted.emit(
            f"OneBot /bot_exit returned HTTP {response.status_code}."
        )

    def _handle_logout_error(self, _error):
        self.napcat_service.log_emitted.emit(
            "OneBot /bot_exit connection closed before confirmation."
        )

    def _handle_napcat_stop_completed(self, success, _message):
        if not self._waiting_for_napcat_stop:
            return
        self._waiting_for_napcat_stop = False
        self._emit_logout_stop_result(stopped_internal=success)

    def _emit_logout_stop_result(self, stopped_internal):
        quick_login_cleared = self._pending_quick_login_cleared
        self._logout_stop_in_progress = False
        self._pending_quick_login_cleared = False
        if quick_login_cleared and stopped_internal:
            message = "QQ 快速登录已清除，内部 NapCat 已停止。"
        elif quick_login_cleared:
            message = "QQ 快速登录已清除，但没有可停止的内部 NapCat。"
        elif stopped_internal:
            message = "内部 NapCat 已停止，但快速登录账号未清除；下次启动可能仍会登录原账号。"
        else:
            message = "快速登录账号未清除，且没有可停止的内部 NapCat；下次启动可能仍会登录原账号。"
        self.status_updated.emit(message)
        self.logout_stop_finished.emit(
            quick_login_cleared and stopped_internal, message
        )

    def _handle_webui_detected(self, url, token):
        self._cached_webui_url = url
        self._cached_webui_token = token
        if self._is_polling:
            self._setup_and_authenticate_webui()

    def _setup_and_authenticate_webui(self):
        if not self._cached_webui_url:
            return False
        self._waiting_for_webui = False
        self.webui_service.setup(
            self._cached_webui_url, self._cached_webui_token
        )
        self.webui_service.authenticate()
        return True

    def _poll_status(self):
        if not self._is_polling or self._current_request_in_flight:
            return
            
        if not self.webui_service.base_url:
            self._waiting_for_webui = True
            # Fallback: check if OneBot API is online. If online, it means login is completed successfully!
            if self.napcat_service.check_external_status() == "RUNNING (External)":
                self.poll_timer.stop()
                self._is_polling = False
                self.status_updated.emit("QQ 登录成功")
                self.login_success.emit()
            return
            
        self._current_request_in_flight = True
        self.webui_service.check_login_status()

    def _handle_status_result(self, data):
        self._current_request_in_flight = False
        if not self._is_polling:
            return
            
        is_login = data.get("isLogin", False)
        qrcode_url = data.get("qrcodeurl")
        login_error = data.get("loginError", "")
        
        if is_login:
            self.poll_timer.stop()
            self._is_polling = False
            self.status_updated.emit("QQ 登录成功")
            # Clear sensitive
            self.webui_service.credential = ""
            self.login_success.emit()
            return
            
        if "过期" in str(login_error):
            self.status_updated.emit("二维码已过期，请刷新")
            return
            
        if qrcode_url:
            self.status_updated.emit("等待扫码")
            self.qrcode_ready.emit("url", qrcode_url)
        else:
            # Try to get qrcode specifically
            self._current_request_in_flight = True
            self.webui_service.get_qrcode()

    def _handle_status_error(self, err):
        self._current_request_in_flight = False
        if not self._is_polling:
            return
        # If WebUI failed, maybe we have fallback QR
        if self._fallback_qr_url:
            self.qrcode_ready.emit("url", self._fallback_qr_url)
            self.status_updated.emit("等待扫码 (日志 URL Fallback)")
        elif self._fallback_qr_file:
            self.qrcode_ready.emit("file", self._fallback_qr_file)
            self.status_updated.emit("等待扫码 (本地图片 Fallback)")
        else:
            self.status_updated.emit(f"获取状态失败: {err}")

    def _handle_qrcode_result(self, res):
        self._current_request_in_flight = False
        if res == "REFRESHED_SIGNAL":
            # Just let the next poll handle it
            return
        if self._is_polling:
            self.status_updated.emit("等待扫码")
            self.qrcode_ready.emit("url", res)

    def _handle_qrcode_error(self, err):
        self._current_request_in_flight = False
        if not self._is_polling:
            return
        # Fallbacks
        if self._fallback_qr_url:
            self.qrcode_ready.emit("url", self._fallback_qr_url)
        elif self._fallback_qr_file:
            self.qrcode_ready.emit("file", self._fallback_qr_file)

    def _handle_fallback_url(self, url):
        self._fallback_qr_url = url
        if self._is_polling:
            self.qrcode_ready.emit("url", url)
            self.status_updated.emit("等待扫码")

    def _handle_fallback_file(self, path):
        if os.path.exists(path):
            self._fallback_qr_file = path
            if self._is_polling:
                self.qrcode_ready.emit("file", path)
                self.status_updated.emit("等待扫码")

    def _handle_process_failed(self, exit_code):
        if self._is_polling and self._waiting_for_webui:
            self.poll_timer.stop()
            self._is_polling = False
            self.status_updated.emit(f"NapCat.Shell 启动失败\n进程退出代码：{exit_code}\nNapCat 启动目录可能不正确。\n请确认选择的是 NapCat 安装目录中的 launcher.bat。")
            self.login_failed.emit(f"NapCat process exited with code {exit_code}")
