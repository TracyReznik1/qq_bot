from PySide6.QtWidgets import QLineEdit, QWidget, QHBoxLayout, QPushButton, QStyle
from PySide6.QtCore import Qt

class PasswordField(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.line_edit = QLineEdit()
        self.line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        
        self.toggle_btn = QPushButton("Show")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setFixedWidth(50)
        self.toggle_btn.toggled.connect(self.on_toggle)

        layout.addWidget(self.line_edit)
        layout.addWidget(self.toggle_btn)

    def on_toggle(self, checked):
        if checked:
            self.line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_btn.setText("Hide")
        else:
            self.line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_btn.setText("Show")

    def text(self):
        return self.line_edit.text()

    def setText(self, text):
        self.line_edit.setText(text)
