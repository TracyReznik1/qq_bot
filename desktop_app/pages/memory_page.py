import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QTextEdit, QPushButton, QMessageBox

class MemoryPage(QWidget):
    def __init__(self, memory_service, bot_service, parent=None):
        super().__init__(parent)
        self.memory_service = memory_service
        self.bot_service = bot_service
        self.current_file = None
        
        layout = QHBoxLayout(self)
        
        # Left side: File list
        left_layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentTextChanged.connect(self.on_file_selected)
        
        btn_refresh = QPushButton("Refresh List")
        btn_refresh.clicked.connect(self.refresh_list)
        
        left_layout.addWidget(btn_refresh)
        left_layout.addWidget(self.list_widget)
        
        # Right side: Editor
        right_layout = QVBoxLayout()
        self.editor = QTextEdit()
        
        from desktop_app.utils.font_utils import system_monospace_font
        self.editor.setFont(system_monospace_font())
        
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save / Format")
        self.btn_save.clicked.connect(self.save_memory)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_memory)
        
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_delete)
        
        right_layout.addWidget(self.editor)
        right_layout.addLayout(btn_layout)
        
        layout.addLayout(left_layout, 1)
        layout.addLayout(right_layout, 2)
        
        self.bot_service.state_changed.connect(self.update_readonly_state)
        self.refresh_list()
        self.update_readonly_state("Stopped")

    def update_readonly_state(self, state: str):
        is_running = state in ["Running", "Starting"]
        self.editor.setReadOnly(is_running)
        self.btn_save.setEnabled(not is_running)
        self.btn_delete.setEnabled(not is_running)

    def refresh_list(self):
        self.list_widget.clear()
        files = self.memory_service.list_memories()
        self.list_widget.addItems(files)
        self.editor.clear()
        self.current_file = None

    def on_file_selected(self, current_text: str):
        if not current_text:
            return
        self.current_file = current_text
        content = self.memory_service.load_raw(current_text)
        self.editor.setPlainText(content)

    def save_memory(self):
        if not self.current_file:
            return
            
        text = self.editor.toPlainText()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", f"Invalid JSON format:\n{str(e)}")
            return
            
        success, msg = self.memory_service.save_memory(self.current_file, data)
        if success:
            QMessageBox.information(self, "Success", "Memory saved successfully.")
            # Reload formatted
            self.on_file_selected(self.current_file)
        else:
            QMessageBox.critical(self, "Error", msg)

    def delete_memory(self):
        if not self.current_file:
            return
            
        reply = QMessageBox.question(self, 'Delete Memory', f"Are you sure you want to delete {self.current_file}?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.memory_service.delete_memory(self.current_file):
                self.refresh_list()
            else:
                QMessageBox.critical(self, "Error", "Failed to delete file.")
