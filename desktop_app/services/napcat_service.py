import os
import re
from PySide6.QtCore import QObject, Signal, QProcess, QTimer
import urllib.request

from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class ProcessLaunchSpec:
    program: str
    arguments: list[str]
    working_directory: str

class NapCatService(QObject):
    log_emitted = Signal(str)
    state_changed = Signal(str)
    
    # Signals for extracted info
    webui_detected = Signal(str, str) # url, token
    qrcode_url_detected = Signal(str) # url
    qrcode_file_detected = Signal(str) # path
    process_failed = Signal(int) # exit code
    startup_error = Signal(str)
    admin_elevation_required = Signal(bool) # bool: has_user_bat
    stop_completed = Signal(bool, str)

    def __init__(self, settings_service):
        super().__init__()
        self.settings_service = settings_service
        self.process = QProcess()
        # Ensure separate channels for stdout/stderr? Or merged? The prompt allows Merged if explained.
        # Separate channels are fine.
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.stateChanged.connect(self.handle_state_changed)
        self.process.finished.connect(self.handle_finished)
        self.process.errorOccurred.connect(self.handle_error)
        self._tree_killer = QProcess(self)
        self._tree_killer.errorOccurred.connect(self._handle_tree_kill_error)
        self._tree_killer.finished.connect(self._handle_tree_kill_finished)
        
        self.stdout_buffer = b""
        self.stderr_buffer = b""
        
        # Regex for ANSI
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        # Regex for specific info
        self.webui_regex = re.compile(r'WebUi User Panel Url:\s*(https?://[^\s\?]+(?:\?token=([^\s]+))?)')
        self.qr_url_regex = re.compile(r'二维码解码URL:\s*(https?://\S+)')
        self.qr_file_regex = re.compile(r'二维码已保存到\s*([^\r\n]+)')

        self.error_keywords = [
            "provided QQ path is invalid",
            "is not recognized as an internal or external command",
            "The system cannot find the path specified",
            "Access is denied",
            "拒绝访问",
            "找不到指定的路径",
            "不是内部或外部命令"
        ]
        
        self._current_state = "STOPPED"
        self._qprocess_timeout_timer = None
        self._webui_timeout_timer = None
        self._stop_requested = False

    def is_running_internally(self):
        return self._current_state in ["RUNNING", "WAITING_WEBUI"]

    def check_external_status(self) -> str:
        onebot_url = self.settings_service.get("ONEBOT_API_URL", "http://127.0.0.1:3000")
        try:
            req = urllib.request.Request(f"{onebot_url}/get_status")
            with urllib.request.urlopen(req, timeout=0.5) as response:
                if response.status == 200:
                    return "RUNNING (External)"
        except Exception:
            pass
        return "STOPPED"

    def build_napcat_launch_spec(self, configured_path: str) -> ProcessLaunchSpec:
        p = Path(configured_path).resolve()
        working_dir = str(p.parent)
        
        if p.suffix.lower() in ['.bat', '.cmd']:
            return ProcessLaunchSpec(
                program="cmd.exe",
                arguments=["/c", "call", p.name],
                working_directory=working_dir
            )
        else:
            return ProcessLaunchSpec(
                program=str(p),
                arguments=[],
                working_directory=working_dir
            )

    def check_napcat_integrity(self, directory: Path) -> list[str]:
        required_files = [
            "NapCatWinBootMain.exe",
            "NapCatWinBootHook.dll",
            "napcat.mjs",
            "qqnt.json"
        ]
        missing = []
        for f in required_files:
            if not (directory / f).exists():
                missing.append(f)
        return missing

    def set_state(self, new_state: str):
        if self._current_state != new_state:
            self._current_state = new_state
            self.state_changed.emit(new_state)

    def start(self, path: str):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
            
        self.set_state("STARTING_WRAPPER")

        path = path.strip()
        if not path or not os.path.exists(path):
            msg = "NapCat executable path is invalid."
            self.log_emitted.emit(msg)
            self.startup_error.emit(msg)
            self.process_failed.emit(1)
            self.set_state("FAILED")
            return

        p = Path(path).resolve()
        
        # Integrity check for bat/cmd
        if p.suffix.lower() in ['.bat', '.cmd']:
            missing = self.check_napcat_integrity(p.parent)
            if missing:
                msg = "NapCat.Shell 安装目录不完整。\n缺少文件：\n- " + "\n- ".join(missing) + "\n请选择 NapCat.Shell 安装目录中的 launcher.bat，不要将 launcher.bat 单独复制到其他目录。"
                self.log_emitted.emit(msg)
                self.startup_error.emit(msg)
                self.process_failed.emit(1)
                self.set_state("FAILED")
                return
                
            # Check admin ONLY for launcher.bat or launcher-win10.bat
            # Scripts containing "user" don't need admin
            if p.name.lower() in ['launcher.bat', 'launcher-win10.bat']:
                import ctypes
                try:
                    is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                except:
                    is_admin = False
                    
                if not is_admin:
                    has_user_bat = (p.parent / "launcher-user.bat").exists()
                    self.log_emitted.emit("当前选择的 NapCat 脚本需要管理员权限，正在请求提权...")
                    self.admin_elevation_required.emit(has_user_bat)
                    self.set_state("FAILED")
                    return

        spec = self.build_napcat_launch_spec(path)

        self.stdout_buffer = b""
        self.stderr_buffer = b""

        self.log_emitted.emit(f"正在启动 NapCat.Shell\n启动文件：{p}\n工作目录：{spec.working_directory}\n启动方式：{'批处理文件' if p.suffix.lower() in ['.bat', '.cmd'] else '可执行文件'}")
        
        self.process.setWorkingDirectory(spec.working_directory)
        self.process.start(spec.program, spec.arguments)
        
        # Close write channel to prevent 'pause' from hanging indefinitely
        self.process.closeWriteChannel()
        
        # Timeout check
        self._qprocess_timeout_timer = QTimer.singleShot(5000, self._check_qprocess_startup_timeout)
        self._webui_timeout_timer = QTimer.singleShot(30000, self._check_webui_startup_timeout)

    def _check_qprocess_startup_timeout(self):
        self._qprocess_timeout_timer = None
        if self._current_state == "STARTING_WRAPPER":
            if self.process.state() == QProcess.ProcessState.NotRunning:
                self.flush_buffers()
                msg = "NapCat 启动没有返回结果，进程未成功创建。请检查启动文件和权限。"
                self.log_emitted.emit(msg)
                self.startup_error.emit(msg)
                self.process_failed.emit(1)
                self.set_state("FAILED")

    def _check_webui_startup_timeout(self):
        self._webui_timeout_timer = None
        if self._current_state in ["STARTING_WRAPPER", "STARTING_NAPCAT"]:
            self.flush_buffers()
            msg = "NapCat 启动超时 (30秒内未检测到 WebUI URL 或控制台二维码)。"
            self.log_emitted.emit(msg)
            self.startup_error.emit(msg)
            self.process_failed.emit(1)
            self.set_state("FAILED")
            self.stop()
        elif self._current_state == "WAITING_WEBUI":
            self.log_emitted.emit("NapCat WebUI 未能连通，但已成功从日志获取控制台二维码，将继续等待登录。")

    def stop(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return False
        if self._stop_requested:
            return True

        self._stop_requested = True
        self.set_state("STOPPING")
        self.log_emitted.emit("Stopping internally launched NapCat...")

        pid = int(self.process.processId())
        if os.name == "nt" and pid > 0:
            self._tree_killer.start(
                "taskkill", ["/PID", str(pid), "/T", "/F"]
            )
        else:
            self.process.terminate()
        QTimer.singleShot(3000, self._force_kill_managed_process)
        return True

    def _force_kill_managed_process(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _handle_tree_kill_error(self, _error):
        self.log_emitted.emit(
            "NapCat process-tree stop failed; killing wrapper process."
        )
        self._force_kill_managed_process()

    def _handle_tree_kill_finished(self, exit_code, _exit_status):
        if exit_code != 0:
            self._force_kill_managed_process()

    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data()
        self.stdout_buffer += data
        self.stdout_buffer = self.process_buffer(self.stdout_buffer)

    def handle_stderr(self):
        data = self.process.readAllStandardError().data()
        self.stderr_buffer += data
        self.stderr_buffer = self.process_buffer(self.stderr_buffer)
        
    def flush_buffers(self):
        if self.stdout_buffer:
            self.process_buffer(self.stdout_buffer + b'\n')
            self.stdout_buffer = b""
        if self.stderr_buffer:
            self.process_buffer(self.stderr_buffer + b'\n')
            self.stderr_buffer = b""
        
    def process_buffer(self, buffer: bytes) -> bytes:
        # Prevent buffer from growing infinitely if no newlines
        if len(buffer) > 1024 * 1024:
            buffer = buffer[-1024:]
            
        while b'\n' in buffer or b'\r' in buffer:
            if b'\n' in buffer:
                line_bytes, buffer = buffer.split(b'\n', 1)
            else:
                line_bytes, buffer = buffer.split(b'\r', 1)
                
            if not line_bytes.strip():
                continue
                
            # Decode using system encoding fallback
            try:
                line = line_bytes.decode('utf-8')
            except UnicodeDecodeError:
                line = line_bytes.decode('gbk', errors='replace')
                
            line = line.strip()
            if not line:
                continue
                
            # Strip ANSI
            clean_line = self.ansi_escape.sub('', line)
            
            self.parse_and_log(clean_line)
            
        return buffer

    def parse_and_log(self, line: str):
        # 0. Check Errors
        for keyword in self.error_keywords:
            if keyword.lower() in line.lower():
                self.log_emitted.emit(line)
                msg = f"检测到启动错误：{line}"
                self.log_emitted.emit(msg)
                self.startup_error.emit(msg)
                self.process_failed.emit(1)
                self.set_state("FAILED")
                self.stop()
                return

        # Advance state to STARTING_NAPCAT if we see napcat output
        if self._current_state == "STARTING_WRAPPER":
            if "NapCat" in line or "QQNT" in line or "Boot Command" in line or "NapCat Shell App Loading" in line:
                self.set_state("STARTING_NAPCAT")

        if self._current_state in ["STARTING_WRAPPER", "STARTING_NAPCAT"]:
            if "二维码" in line or "WebUi" in line or "网络已连接" in line or "获取" in line:
                self.set_state("WAITING_WEBUI")

        # 1. Check WebUI
        webui_match = self.webui_regex.search(line)
        if webui_match:
            full_url = webui_match.group(1)
            token = webui_match.group(2) or ""
            # Redact token from log
            if token:
                redacted_line = line.replace(f"token={token}", "token=<REDACTED>")
                self.log_emitted.emit(redacted_line)
            else:
                self.log_emitted.emit(line)
            # Emit signal
            base_url = full_url.split("?")[0] if "?" in full_url else full_url
            self.webui_detected.emit(base_url, token)
            
            # Successfully running!
            if self._webui_timeout_timer:
                # Need to cancel timer, wait QTimer can't be cancelled by variable easily if singleShot string, wait. QTimer.singleShot doesn't return timer.
                # I should just check state in timeout.
                pass
            self.set_state("RUNNING")
            return
            
        # 2. Check QR URL
        qr_url_match = self.qr_url_regex.search(line)
        if qr_url_match:
            url = qr_url_match.group(1)
            redacted_line = line.replace(url, "<REDACTED_URL>")
            self.log_emitted.emit("已从 NapCat 输出取得 QQ 登录二维码。") # Completely rewrite log to hide URL
            self.qrcode_url_detected.emit(url)
            self.set_state("WAITING_WEBUI")
            return
            
        # 3. Check QR File
        qr_file_match = self.qr_file_regex.search(line)
        if qr_file_match:
            path = qr_file_match.group(1).strip().strip('"\'')
            self.log_emitted.emit(line)
            self.qrcode_file_detected.emit(path)
            self.set_state("WAITING_WEBUI")
            return
            
        self.log_emitted.emit(line)

    def handle_state_changed(self, state):
        if state == QProcess.ProcessState.NotRunning:
            if self._current_state not in ["FAILED", "STOPPED"]:
                self.set_state("STOPPED")
        elif state == QProcess.ProcessState.Starting:
            pass # already handled in start()
        elif state == QProcess.ProcessState.Running:
            pass # wait for WebUI to become RUNNING

    def handle_finished(self, exit_code, exit_status):
        self.flush_buffers()
        self.log_emitted.emit(f"NapCat process finished with code {exit_code}")
        if self._stop_requested:
            self._stop_requested = False
            self.set_state("STOPPED")
            self.stop_completed.emit(True, "内部 NapCat 已停止。")
            return
        if exit_code != 0 and self._current_state != "FAILED":
            self.process_failed.emit(exit_code)
            self.set_state("FAILED")
        elif self._current_state != "FAILED":
            self.set_state("STOPPED")

    def handle_error(self, error):
        self.flush_buffers()
        if self._stop_requested:
            self.log_emitted.emit(f"NapCat process stopping: {error}")
            return
        msg = f"NapCat process error occurred: {error}"
        self.log_emitted.emit(msg)
        self.startup_error.emit(msg)
        self.process_failed.emit(1)
        self.set_state("FAILED")
