import hashlib
import json
import requests
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Qt

class WebUIRequestTask(QRunnable):
    def __init__(self, url, method="POST", headers=None, json_data=None, timeout=5, callback=None, error_callback=None):
        super().__init__()
        self.url = url
        self.method = method
        self.headers = headers or {}
        self.json_data = json_data
        self.timeout = timeout
        self.callback = callback
        self.error_callback = error_callback

    def run(self):
        try:
            if self.method == "POST":
                response = requests.post(self.url, headers=self.headers, json=self.json_data, timeout=self.timeout)
            else:
                response = requests.get(self.url, headers=self.headers, timeout=self.timeout)
            
            if self.callback:
                self.callback(response)
        except Exception as e:
            if self.error_callback:
                self.error_callback(str(e))

class NapCatWebUIService(QObject):
    log_emitted = Signal(str)
    auth_success = Signal()
    auth_failed = Signal(str)
    
    login_status_result = Signal(dict)
    login_status_error = Signal(str)
    
    qrcode_result = Signal(str) # url
    qrcode_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.base_url = ""
        self.token = ""
        self.credential = ""
        self.thread_pool = QThreadPool.globalInstance()
        self.is_authenticating = False

    def setup(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.credential = ""

    def authenticate(self):
        if not self.base_url:
            self.auth_failed.emit("Base URL not set")
            return
            
        if self.is_authenticating:
            return
            
        self.is_authenticating = True
        
        # Calculate hash
        # sha256((webui_token + ".napcat").encode("utf-8")).hexdigest()
        raw = f"{self.token}.napcat".encode("utf-8")
        hash_val = hashlib.sha256(raw).hexdigest()
        
        url = f"{self.base_url}/api/auth/login"
        
        def on_success(response):
            self.is_authenticating = False
            try:
                data = response.json()
                if response.status_code == 200 and data.get("code") == 0:
                    self.credential = data.get("data", {}).get("token") or data.get("data", {}).get("Credential") or ""
                    if self.credential:
                        self.log_emitted.emit("NapCat WebUI 鉴权成功")
                        self.auth_success.emit()
                    else:
                        self.auth_failed.emit("Login returned 200 but no Credential/token found")
                else:
                    self.log_emitted.emit("NapCat WebUI 鉴权失败")
                    self.auth_failed.emit(f"Auth error: {data}")
            except Exception as e:
                self.log_emitted.emit("NapCat WebUI 鉴权失败")
                self.auth_failed.emit(f"Parse error: {str(e)}")
                
        def on_error(err):
            self.is_authenticating = False
            self.log_emitted.emit("NapCat WebUI 鉴权失败")
            self.auth_failed.emit(err)
            
        task = WebUIRequestTask(
            url=url,
            method="POST",
            json_data={"hash": hash_val},
            callback=on_success,
            error_callback=on_error,
            timeout=5
        )
        self.thread_pool.start(task)

    def _get_headers(self):
        if self.credential:
            return {"Authorization": f"Bearer {self.credential}"}
        return {}

    def check_login_status(self, is_retry=False):
        if not self.base_url:
            self.login_status_error.emit("Base URL not set")
            return
            
        url = f"{self.base_url}/api/QQLogin/CheckLoginStatus"
        
        def on_success(response):
            if response.status_code in [401, 403]:
                if not is_retry:
                    self.log_emitted.emit("WebUI Token expired, re-authenticating...")
                    # Re-auth and retry
                    def on_auth_success():
                        self.check_login_status(is_retry=True)
                    def on_auth_failed(err):
                        self.login_status_error.emit(f"Re-auth failed: {err}")
                    self.auth_success.connect(on_auth_success, type=Qt.UniqueConnection)
                    self.auth_failed.connect(on_auth_failed, type=Qt.UniqueConnection)
                    self.authenticate()
                    return
                else:
                    self.login_status_error.emit("Unauthorized")
                    return
            try:
                data = response.json()
                self.login_status_result.emit(data.get("data", {}))
            except Exception as e:
                self.login_status_error.emit(str(e))
                
        task = WebUIRequestTask(
            url=url,
            headers=self._get_headers(),
            callback=on_success,
            error_callback=self.login_status_error.emit
        )
        self.thread_pool.start(task)

    def get_qrcode(self, is_retry=False):
        if not self.base_url:
            self.qrcode_error.emit("Base URL not set")
            return
            
        url = f"{self.base_url}/api/QQLogin/GetQQLoginQrcode"
        
        def on_success(response):
            if response.status_code in [401, 403]:
                if not is_retry:
                    def on_auth_success():
                        self.get_qrcode(is_retry=True)
                    self.auth_success.connect(on_auth_success, type=Qt.UniqueConnection)
                    self.authenticate()
                    return
                else:
                    self.qrcode_error.emit("Unauthorized")
                    return
            try:
                data = response.json()
                qrcode_url = data.get("data", {}).get("qrcode") or data.get("data", {}).get("qrcodeurl")
                if qrcode_url:
                    self.qrcode_result.emit(qrcode_url)
                else:
                    self.qrcode_error.emit("No qrcode in response")
            except Exception as e:
                self.qrcode_error.emit(str(e))
                
        task = WebUIRequestTask(
            url=url,
            headers=self._get_headers(),
            callback=on_success,
            error_callback=self.qrcode_error.emit
        )
        self.thread_pool.start(task)
        
    def refresh_qrcode(self, is_retry=False):
        if not self.base_url:
            self.qrcode_error.emit("Base URL not set")
            return
            
        url = f"{self.base_url}/api/QQLogin/RefreshQRcode"
        
        def on_success(response):
            if response.status_code in [401, 403]:
                if not is_retry:
                    def on_auth_success():
                        self.refresh_qrcode(is_retry=True)
                    self.auth_success.connect(on_auth_success, type=Qt.UniqueConnection)
                    self.authenticate()
                    return
                else:
                    self.qrcode_error.emit("Unauthorized")
                    return
            # Refresh returns nothing useful, we should check status or get qr again
            # The calling service should coordinate
            self.qrcode_result.emit("REFRESHED_SIGNAL")
            
        task = WebUIRequestTask(
            url=url,
            headers=self._get_headers(),
            callback=on_success,
            error_callback=self.qrcode_error.emit
        )
        self.thread_pool.start(task)
