import os
import shlex
import urllib.request
import urllib.error
from PySide6.QtCore import QObject, Signal, QProcess

class NapCatService(QObject):
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

    def is_running_internally(self):
        return self.process.state() == QProcess.ProcessState.Running

    def check_external_status(self) -> str:
        """Checks if OneBot is reachable and returns status."""
        onebot_url = self.settings_service.get("ONEBOT_API_URL", "http://127.0.0.1:3000")
        try:
            req = urllib.request.Request(f"{onebot_url}/get_status")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return "Running (External/Internal)"
        except Exception:
            pass
        return "Stopped"

    def start(self, path: str):
        if self.is_running_internally():
            return
            
        path = path.strip()
        if not path or not os.path.exists(path):
            self.log_emitted.emit("NapCat executable path is invalid.")
            return

        self.log_emitted.emit(f"Starting NapCat from {path}")
        
        if path.lower().endswith('.bat') or path.lower().endswith('.cmd'):
            self.process.start("cmd.exe", ["/c", path])
        else:
            self.process.start(path, [])

    def stop(self):
        if self.is_running_internally():
            self.log_emitted.emit("Stopping internally launched NapCat...")
            self.process.terminate()

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
            self.state_changed.emit("Running (Internal)")

    def handle_finished(self, exit_code, exit_status):
        self.log_emitted.emit(f"NapCat process finished with code {exit_code}")
        self.state_changed.emit("Stopped")
