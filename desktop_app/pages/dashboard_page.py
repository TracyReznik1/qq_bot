from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox
from PySide6.QtCore import Qt

class DashboardPage(QWidget):
    def __init__(self, bot_service, napcat_service, diagnostics_service, parent=None):
        super().__init__(parent)
        self.bot_service = bot_service
        self.napcat_service = napcat_service
        self.diagnostics_service = diagnostics_service
        
        layout = QVBoxLayout(self)
        
        # Status Group
        status_group = QGroupBox("System Status")
        status_layout = QVBoxLayout(status_group)
        
        self.lbl_bot = QLabel("Bot Status: Unknown")
        self.lbl_napcat = QLabel("NapCat Status: Unknown")
        
        status_layout.addWidget(self.lbl_bot)
        status_layout.addWidget(self.lbl_napcat)
        layout.addWidget(status_group)
        
        # Controls Group
        controls_group = QGroupBox("Quick Controls")
        controls_layout = QHBoxLayout(controls_group)
        
        self.btn_start_bot = QPushButton("Start Bot")
        self.btn_stop_bot = QPushButton("Stop Bot")
        self.btn_restart_bot = QPushButton("Restart Bot")
        
        self.btn_start_bot.clicked.connect(self.bot_service.start)
        self.btn_stop_bot.clicked.connect(self.bot_service.request_stop)
        self.btn_restart_bot.clicked.connect(self.restart_bot)
        
        controls_layout.addWidget(self.btn_start_bot)
        controls_layout.addWidget(self.btn_stop_bot)
        controls_layout.addWidget(self.btn_restart_bot)
        
        layout.addWidget(controls_group)
        layout.addStretch()
        
        # Connections
        self.bot_service.state_changed.connect(self.update_bot_status)
        self.napcat_service.state_changed.connect(self.update_napcat_status)
        
        # Initial status
        self.update_bot_status("Stopped")
        self.update_napcat_status("Stopped")

    def restart_bot(self):
        self.bot_service.force_kill()
        self.bot_service.start()

    def update_bot_status(self, state: str):
        self.lbl_bot.setText(f"Bot Status: {state}")
        is_running = state in ["Running", "Starting"]
        self.btn_start_bot.setEnabled(not is_running)
        self.btn_stop_bot.setEnabled(is_running)
        self.btn_restart_bot.setEnabled(is_running)

    def update_napcat_status(self, state: str):
        self.lbl_napcat.setText(f"NapCat Status: {state}")
