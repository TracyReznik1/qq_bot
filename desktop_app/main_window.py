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
        self.dashboard_page = DashboardPage(
            self.services['bot'],
            self.services['napcat'],
            self.services['diagnostics'],
            self.services['webui'],
            self.services['qq_login'],
        )
        self.napcat_page = NapCatPage(
            self.services['settings'],
            self.services['napcat'],
            self.services['webui'],
            self.services['qq_login'],
        )
        pages_info = [
            ("Dashboard", self.dashboard_page),
            ("Settings & Models", SettingsPage(self.services['settings'])),
            ("NapCat & QQ", self.napcat_page),
            ("Memory Management", MemoryPage(self.services['memory'], self.services['bot'])),
            ("Logs", LogsPage(self.services['bot'], self.services['napcat'])),
            ("Diagnostics", DiagnosticsPage(self.services['diagnostics'])),
        ]
        
        for name, widget in pages_info:
            self.sidebar.addItem(name)
            self.stacked_widget.addWidget(widget)

        # Connect NapCat service signals
        napcat_svc = self.services['napcat']
        napcat_svc.startup_error.connect(self.handle_startup_error)
        napcat_svc.admin_elevation_required.connect(self.handle_admin_elevation)
        self.dashboard_page.logout_stop_requested.connect(
            self.request_logout_and_stop
        )
        self.napcat_page.logout_stop_requested.connect(
            self.request_logout_and_stop
        )
        self.services['qq_login'].logout_stop_finished.connect(
            self.handle_logout_stop_finished
        )

    def request_logout_and_stop(self):
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "切换 QQ 账号",
            "这会退出当前 QQ 并停止由管理器启动的 NapCat。Bot 将暂时无法收发消息，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self.services['qq_login'].logout_and_stop():
            self.dashboard_page.set_logout_stop_busy(True)
            self.napcat_page.set_logout_stop_busy(True)

    def handle_logout_stop_finished(self, success, message):
        from PySide6.QtWidgets import QMessageBox

        self.dashboard_page.set_logout_stop_busy(False)
        self.napcat_page.set_logout_stop_busy(False)
        if success:
            QMessageBox.information(self, "切换 QQ 账号", message)
        else:
            QMessageBox.warning(self, "切换 QQ 账号", message)

    def handle_startup_error(self, msg):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "NapCat 启动失败", msg)

    def handle_admin_elevation(self, has_user_bat):
        from PySide6.QtWidgets import QMessageBox
        import sys
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("需要管理员权限")
        msg_box.setIcon(QMessageBox.Warning)
        
        if has_user_bat:
            msg_box.setText("当前选择的 NapCat 启动脚本 (launcher.bat) 需要管理员权限。\n检测到普通用户版本：launcher-user.bat")
            btn_user = msg_box.addButton("使用普通用户版本启动", QMessageBox.AcceptRole)
            btn_admin = msg_box.addButton("以管理员身份重启 ATRI", QMessageBox.ActionRole)
            btn_cancel = msg_box.addButton("取消", QMessageBox.RejectRole)
        else:
            msg_box.setText("当前 NapCat 启动脚本需要管理员权限。\n\n请以管理员身份重新运行 ATRI QQBot Manager。")
            btn_admin = msg_box.addButton("以管理员身份重启", QMessageBox.AcceptRole)
            btn_cancel = msg_box.addButton("取消", QMessageBox.RejectRole)
            btn_user = None

        msg_box.exec()
        
        if btn_user and msg_box.clickedButton() == btn_user:
            self.start_napcat_user_mode()
        elif msg_box.clickedButton() == btn_admin:
            self.restart_as_admin()

    def start_napcat_user_mode(self):
        from pathlib import Path
        napcat_svc = self.services['napcat']
        settings = napcat_svc.settings_service
        current_path = settings.get("NAPCAT_PATH", "")
        if current_path:
            p = Path(current_path)
            new_path = p.parent / "launcher-user.bat"
            settings.set("NAPCAT_PATH", str(new_path))
            napcat_svc.start(str(new_path))

    def restart_as_admin(self):
        import ctypes
        import sys
        from PySide6.QtWidgets import QApplication
        
        # Request elevation
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv[1:]), None, 1)
        if ret > 32:
            QApplication.quit()
