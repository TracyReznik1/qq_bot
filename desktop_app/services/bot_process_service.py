import sys
import os
from PySide6.QtCore import QObject, Signal, QProcess, QProcessEnvironment, QTimer

from desktop_app.services.settings_service import SENSITIVE_KEYS
from desktop_app.services.secret_service import SecretService

from desktop_app.utils.path_utils import build_core_process_command

class BotProcessService(QObject):
    log_emitted = Signal(str)
    state_changed = Signal(str)
    restart_started = Signal()
    restart_finished = Signal(bool, str)

    def __init__(self, settings_service):
        super().__init__()
        self.settings_service = settings_service
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.stateChanged.connect(self.handle_state_changed)
        self.process.finished.connect(self.handle_finished)
        self.process.errorOccurred.connect(self.handle_error)
        self._restart_pending = False
        self._restart_in_progress = False

    def is_running(self):
        return self.process.state() == QProcess.ProcessState.Running

    def _build_environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        
        # Inject normal settings
        for k, v in self.settings_service.get_all().items():
            env.insert(str(k), str(v))
            
        # Inject secrets
        for k in SENSITIVE_KEYS:
            val = SecretService.get_secret(k)
            if val:
                env.insert(k, val)
                
        # Disable buffering for Python stdout/stderr so logs appear immediately
        env.insert("PYTHONUNBUFFERED", "1")
        return env

    def start(self):
        if self.is_running():
            return

        env = self._build_environment()
        self.process.setProcessEnvironment(env)

        executable, args = build_core_process_command()

        if not os.path.isfile(executable):
            self.log_emitted.emit(f"FailedToStart: Core executable not found.")
            self.log_emitted.emit(f"Target program: {executable}")
            self.state_changed.emit("Stopped")
            self._finish_restart(False, "Bot 重启失败：核心程序不存在。")
            return False

        self.log_emitted.emit(f"Starting bot process: {executable} {' '.join(args)}")
        self.process.start(executable, args)
        return True

    def request_stop(self):
        if not self._is_active():
            return False
        if os.name == "nt":
            self.log_emitted.emit("Stopping bot process immediately...")
            self.process.kill()
        else:
            self.log_emitted.emit("Requesting bot process to terminate...")
            self.process.terminate()
            QTimer.singleShot(2000, self._force_stop_if_active)
        return True

    def _is_active(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def _force_stop_if_active(self):
        if self._is_active():
            self.log_emitted.emit("Bot did not stop gracefully; killing it...")
            self.process.kill()

    def restart(self):
        if self._restart_in_progress:
            return False
        self._restart_in_progress = True
        self.restart_started.emit()
        if not self._is_active():
            self.start()
            return True
        self._restart_pending = True
        self.request_stop()
        return True

    def force_kill(self):
        if self.is_running():
            self.log_emitted.emit("Killing bot process forcefully...")
            self.process.kill()

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='replace').strip()
        if text:
            self.log_emitted.emit(text)

    def handle_stderr(self):
        data = self.process.readAllStandardError()
        text = bytes(data).decode('utf-8', errors='replace').strip()
        if text:
            self.log_emitted.emit(text)

    def handle_state_changed(self, state):
        if state == QProcess.ProcessState.NotRunning:
            self.state_changed.emit("Stopped")
        elif state == QProcess.ProcessState.Starting:
            self.state_changed.emit("Starting")
        elif state == QProcess.ProcessState.Running:
            self.state_changed.emit("Running")
            if self._restart_in_progress and not self._restart_pending:
                self._finish_restart(True, "Bot 重启成功。")

    def handle_finished(self, exit_code, exit_status):
        self.log_emitted.emit(f"Bot process finished with exit code {exit_code}")
        self.state_changed.emit("Stopped")
        if self._restart_pending:
            self._restart_pending = False
            self.start()

    def handle_error(self, error):
        self.log_emitted.emit(f"Bot process error: {error.name}")
        if self._restart_in_progress and not self._restart_pending:
            self._finish_restart(False, "Bot 重启失败：替代进程未能启动。")

    def _finish_restart(self, success, message):
        if not self._restart_in_progress:
            return
        self._restart_in_progress = False
        self._restart_pending = False
        self.restart_finished.emit(success, message)
