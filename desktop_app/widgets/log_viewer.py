import re
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor
from desktop_app.utils.font_utils import system_monospace_font

class LogViewer(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setFont(system_monospace_font())
        self.max_lines = 1000

    def append_log(self, text: str):
        # Basic redaction for secrets
        text = re.sub(r'Bearer\s+[A-Za-z0-9\-_]+', 'Bearer ***', text)
        text = re.sub(r'base64://[A-Za-z0-9+/=]+', 'base64://***', text)
        
        self.append(text)
        
        # Enforce max lines roughly
        doc = self.document()
        if doc.blockCount() > self.max_lines + 100:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(100):
                cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            
        # Auto scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
