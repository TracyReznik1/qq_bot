from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from desktop_app.widgets.log_viewer import LogViewer

class LogsPage(QWidget):
    def __init__(self, bot_service, napcat_service, parent=None):
        super().__init__(parent)
        self.bot_service = bot_service
        self.napcat_service = napcat_service
        
        layout = QVBoxLayout(self)
        
        self.log_viewer = LogViewer()
        layout.addWidget(self.log_viewer)
        
        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Logs")
        self.btn_clear.clicked.connect(self.log_viewer.clear)
        
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Connect signals
        self.bot_service.log_emitted.connect(self.log_viewer.append_log)
        self.napcat_service.log_emitted.connect(self.log_viewer.append_log)
