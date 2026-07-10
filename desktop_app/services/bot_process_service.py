import sys
import os
from PySide6.QtCore import QObject, Signal, QProcess, QProcessEnvironment

from desktop_app.services.settings_service import SENSITIVE_KEYS
from desktop_app.services.secret_service import SecretService

class BotProcessService(QObject):
    log_emitted = Signal(str)
    state_changed = Signal(str)

    def __init__(self, settings_service):
        super().__init__()
        self.settings_service = settings_service
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.stateChanged.connect(self.handle_state_changed)
        self.process.finished.connect(self.handle_finished)
        self.process.errorOccurred.connect(self.handle_error)

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

        if getattr(sys, "frozen", False):
            # Packaged EXE
            executable = sys.executable
            args = ["--core"]
        else:
            # Dev environment
            executable = sys.executable
            args = ["launcher.py", "--core"]

        self.log_emitted.emit(f"Starting bot process: {executable} {' '.join(args)}")
        self.process.start(executable, args)

    def request_stop(self):
        if self.is_running():
            self.log_emitted.emit("Requesting bot process to terminate...")
            self.process.terminate()

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

    def handle_finished(self, exit_code, exit_status):
        self.log_emitted.emit(f"Bot process finished with exit code {exit_code}")
        self.state_changed.emit("Stopped")

    def handle_error(self, error):
        self.log_emitted.emit(f"Bot process error: {error.name}")
