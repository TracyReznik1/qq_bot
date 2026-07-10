from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QGroupBox, QHBoxLayout, QMessageBox, QFileDialog
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from desktop_app.services.secret_service import SecretService
from desktop_app.widgets.password_field import PasswordField

class NapCatPage(QWidget):
    def __init__(self, settings_service, napcat_service, parent=None):
        super().__init__(parent)
        self.settings_service = settings_service
        self.napcat_service = napcat_service
        
        layout = QVBoxLayout(self)
        
        # Config
        config_group = QGroupBox("NapCat / OneBot Configuration")
        config_layout = QFormLayout(config_group)
        
        self.onebot_url = QLineEdit()
        self.napcat_path = QLineEdit()
        
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_napcat)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.napcat_path)
        path_layout.addWidget(btn_browse)
        
        self.access_token = PasswordField()
        self.callback_secret = PasswordField()
        
        config_layout.addRow("OneBot API URL:", self.onebot_url)
        config_layout.addRow("NapCat Path (.exe/.bat):", path_layout)
        config_layout.addRow("Access Token:", self.access_token)
        config_layout.addRow("Callback Secret:", self.callback_secret)
        layout.addWidget(config_group)
        
        # Controls
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_group)
        
        self.btn_save = QPushButton("Save Settings")
        self.btn_save.clicked.connect(self.save_settings)
        
        self.btn_start = QPushButton("Start NapCat")
        self.btn_start.clicked.connect(self.start_napcat)
        
        self.btn_stop = QPushButton("Stop NapCat (Internal)")
        self.btn_stop.clicked.connect(self.napcat_service.stop)
        
        self.btn_webui = QPushButton("Open WebUI")
        self.btn_webui.clicked.connect(self.open_webui)
        
        controls_layout.addWidget(self.btn_save)
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_stop)
        controls_layout.addWidget(self.btn_webui)
        
        layout.addWidget(controls_group)
        layout.addStretch()
        
        self.load_settings()

    def browse_napcat(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select NapCat", "", "Executables (*.exe *.bat *.cmd);;All Files (*)")
        if path:
            self.napcat_path.setText(path)

    def load_settings(self):
        self.onebot_url.setText(self.settings_service.get("ONEBOT_API_URL", "http://127.0.0.1:3000"))
        self.napcat_path.setText(self.settings_service.get("NAPCAT_PATH", ""))
        self.access_token.setText(SecretService.get_secret("ONEBOT_ACCESS_TOKEN"))
        self.callback_secret.setText(SecretService.get_secret("CALLBACK_SECRET"))

    def save_settings(self):
        self.settings_service.set("ONEBOT_API_URL", self.onebot_url.text().strip())
        self.settings_service.set("NAPCAT_PATH", self.napcat_path.text().strip())
        SecretService.set_secret("ONEBOT_ACCESS_TOKEN", self.access_token.text())
        SecretService.set_secret("CALLBACK_SECRET", self.callback_secret.text())
        QMessageBox.information(self, "Settings", "NapCat settings saved.")

    def start_napcat(self):
        if self.napcat_service.check_external_status() == "Stopped":
            path = self.napcat_path.text().strip()
            self.napcat_service.start(path)
        else:
            QMessageBox.information(self, "NapCat", "NapCat/OneBot is already running externally.")

    def open_webui(self):
        # Infer WebUI from OneBot URL or use fixed if configured
        url = self.onebot_url.text().strip()
        # Generally NapCat webui is on 6099, but we just open a fallback for now
        webui_url = self.settings_service.get("NAPCAT_WEBUI_URL", "http://127.0.0.1:6099/webui")
        QDesktopServices.openUrl(QUrl(webui_url))
