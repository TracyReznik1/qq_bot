from PySide6.QtWidgets import QMainWindow, QStackedWidget, QListWidget, QHBoxLayout, QWidget

from desktop_app.pages.dashboard_page import DashboardPage
from desktop_app.pages.settings_page import SettingsPage
from desktop_app.pages.napcat_page import NapCatPage
from desktop_app.pages.memory_page import MemoryPage
from desktop_app.pages.logs_page import LogsPage
from desktop_app.pages.diagnostics_page import DiagnosticsPage

class MainWindow(QMainWindow):
    def __init__(self, services):
        super().__init__()
        self.setWindowTitle("ATRI QQBot Manager")
        self.resize(900, 600)
        
        self.services = services
        
        # Main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        
        # Stacked Widget for Pages
        self.stacked_widget = QStackedWidget()
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stacked_widget)
        
        self._setup_pages()
        
        self.sidebar.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

    def _setup_pages(self):
        pages_info = [
            ("Dashboard", DashboardPage(self.services['bot'], self.services['napcat'], self.services['diagnostics'])),
            ("Settings & Models", SettingsPage(self.services['settings'])),
            ("NapCat & QQ", NapCatPage(self.services['settings'], self.services['napcat'])),
            ("Memory Management", MemoryPage(self.services['memory'], self.services['bot'])),
            ("Logs", LogsPage(self.services['bot'], self.services['napcat'])),
            ("Diagnostics", DiagnosticsPage(self.services['diagnostics'])),
        ]
        
        for name, widget in pages_info:
            self.sidebar.addItem(name)
            self.stacked_widget.addWidget(widget)
