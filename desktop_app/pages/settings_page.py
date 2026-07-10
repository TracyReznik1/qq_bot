from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QGroupBox, QFileDialog, QMessageBox
from PySide6.QtCore import Qt

from desktop_app.widgets.password_field import PasswordField
from desktop_app.services.secret_service import SecretService

class SettingsPage(QWidget):
    def __init__(self, settings_service, parent=None):
        super().__init__(parent)
        self.settings_service = settings_service
        
        layout = QVBoxLayout(self)
        
        # API Keys
        api_group = QGroupBox("API Keys (Stored securely in Keyring)")
        api_layout = QFormLayout(api_group)
        
        self.gemini_key = PasswordField()
        self.deepseek_key = PasswordField()
        self.tavily_key = PasswordField()
        
        api_layout.addRow("Gemini API Key:", self.gemini_key)
        api_layout.addRow("DeepSeek API Key:", self.deepseek_key)
        api_layout.addRow("Tavily API Key:", self.tavily_key)
        layout.addWidget(api_group)
        
        # Models
        model_group = QGroupBox("Models & General")
        model_layout = QFormLayout(model_group)
        
        self.gemini_model = QLineEdit()
        self.deepseek_model = QLineEdit()
        self.primary_provider = QLineEdit()
        self.primary_model = QLineEdit()
        
        model_layout.addRow("Gemini Model:", self.gemini_model)
        model_layout.addRow("DeepSeek Model:", self.deepseek_model)
        model_layout.addRow("Primary Provider:", self.primary_provider)
        model_layout.addRow("Primary Model:", self.primary_model)
        layout.addWidget(model_group)
        
        # Actions
        btn_layout = QVBoxLayout()
        self.btn_save = QPushButton("Save Settings")
        self.btn_save.clicked.connect(self.save_settings)
        
        self.btn_import = QPushButton("Import from .env")
        self.btn_import.clicked.connect(self.import_env)
        
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_import)
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        self.load_settings()

    def load_settings(self):
        self.gemini_key.setText(SecretService.get_secret("GEMINI_API_KEY"))
        self.deepseek_key.setText(SecretService.get_secret("DEEPSEEK_API_KEY"))
        self.tavily_key.setText(SecretService.get_secret("TAVILY_API_KEY"))
        
        self.gemini_model.setText(self.settings_service.get("GEMINI_MODEL", "gemini-3.1-flash-lite"))
        self.deepseek_model.setText(self.settings_service.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
        self.primary_provider.setText(self.settings_service.get("LLM_PRIMARY_PROVIDER", "gemini"))
        self.primary_model.setText(self.settings_service.get("LLM_PRIMARY_MODEL", "gemini-3.1-flash-lite"))

    def save_settings(self):
        SecretService.set_secret("GEMINI_API_KEY", self.gemini_key.text())
        SecretService.set_secret("DEEPSEEK_API_KEY", self.deepseek_key.text())
        SecretService.set_secret("TAVILY_API_KEY", self.tavily_key.text())
        
        self.settings_service.set("GEMINI_MODEL", self.gemini_model.text().strip())
        self.settings_service.set("DEEPSEEK_MODEL", self.deepseek_model.text().strip())
        self.settings_service.set("LLM_PRIMARY_PROVIDER", self.primary_provider.text().strip())
        self.settings_service.set("LLM_PRIMARY_MODEL", self.primary_model.text().strip())
        
        QMessageBox.information(self, "Settings", "Settings saved successfully.")

    def import_env(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select .env file", "", "Env Files (*.env *.env.example);;All Files (*)")
        if file_path:
            normal, secrets = self.settings_service.import_from_env(file_path)
            self.load_settings()
            QMessageBox.information(self, "Import", f"Imported {normal} normal settings and {secrets} secrets.")
