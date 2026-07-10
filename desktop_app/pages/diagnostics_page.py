from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt

class DiagnosticsPage(QWidget):
    def __init__(self, diagnostics_service, parent=None):
        super().__init__(parent)
        self.diagnostics_service = diagnostics_service
        
        layout = QVBoxLayout(self)
        
        self.btn_run = QPushButton("Run Diagnostics")
        self.btn_run.clicked.connect(self.run_diagnostics)
        
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Component", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.btn_run)
        layout.addWidget(self.table)
        
    def run_diagnostics(self):
        self.btn_run.setEnabled(False)
        self.btn_run.setText("Running...")
        self.table.setRowCount(0)
        self.diagnostics_service.run_diagnostics(self.on_diagnostics_result)
        
    def on_diagnostics_result(self, results: dict):
        self.table.setRowCount(len(results))
        for row, (key, val) in enumerate(results.items()):
            self.table.setItem(row, 0, QTableWidgetItem(key))
            self.table.setItem(row, 1, QTableWidgetItem(val))
            
        self.btn_run.setEnabled(True)
        self.btn_run.setText("Run Diagnostics")
