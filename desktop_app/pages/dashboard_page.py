from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QMessageBox
from PySide6.QtCore import Qt, QProcess, Signal
from desktop_app.widgets.qq_qrcode_dialog import QQQrCodeDialog

class DashboardPage(QWidget):
    logout_stop_requested = Signal()

    def __init__(self, bot_service, napcat_service, diagnostics_service, webui_service, qq_login_service, parent=None):
        super().__init__(parent)
        self.bot_service = bot_service
        self.napcat_service = napcat_service
        self.diagnostics_service = diagnostics_service
        self.webui_service = webui_service
        self.qq_login_service = qq_login_service
        
        layout = QVBoxLayout(self)
        
        # Status Group
        status_group = QGroupBox("System Status")
        status_layout = QVBoxLayout(status_group)
        
        self.lbl_bot = QLabel("Bot Status: Unknown")
        self.lbl_napcat = QLabel("NapCat Status: Unknown")
        self.lbl_qq = QLabel("QQ 登录状态: 未知")
        
        status_layout.addWidget(self.lbl_bot)
        status_layout.addWidget(self.lbl_napcat)
        status_layout.addWidget(self.lbl_qq)
        layout.addWidget(status_group)
        
        # Controls Group
        controls_group = QGroupBox("Quick Controls")
        controls_layout = QHBoxLayout(controls_group)
        
        self.btn_login_qq = QPushButton("QQ 扫码登录")
        self.btn_stop_napcat = QPushButton("退出 QQ 并停止 NapCat")
        self.btn_start_bot = QPushButton("启动 Bot")
        self.btn_stop_bot = QPushButton("停止 Bot")
        self.btn_restart_bot = QPushButton("重启 Bot")
        
        self.btn_login_qq.clicked.connect(self.login_qq)
        self.btn_stop_napcat.clicked.connect(self.logout_stop_requested.emit)
        self.btn_start_bot.clicked.connect(self.start_bot_checked)
        self.btn_stop_bot.clicked.connect(self.bot_service.request_stop)
        self.btn_restart_bot.clicked.connect(self.restart_bot)
        
        controls_layout.addWidget(self.btn_login_qq)
        controls_layout.addWidget(self.btn_stop_napcat)
        controls_layout.addWidget(self.btn_start_bot)
        controls_layout.addWidget(self.btn_stop_bot)
        controls_layout.addWidget(self.btn_restart_bot)
        
        layout.addWidget(controls_group)
        layout.addStretch()
        
        # Connections
        self.bot_service.state_changed.connect(self.update_bot_status)
        self.napcat_service.state_changed.connect(self.update_napcat_status)
        
        self.qq_login_service.login_success.connect(self.on_login_success)
        self.qq_login_service.login_failed.connect(self.on_login_failed)
        self.qq_login_service.status_updated.connect(self.on_login_status_updated)
        
        # Initial status
        self.update_bot_status("Stopped")
        self.update_napcat_status("Stopped")

    def start_bot_checked(self):
        # 1. 检查内部进程是否正在运行 (不管有没有连上 WebUI)
        internal_running = self.napcat_service.process.state() == QProcess.ProcessState.Running
        
        # 2. 检查外部 OneBot 服务是否在运行
        external_running = self.napcat_service.check_external_status() == "RUNNING (External)"
        
        # 3. 检查当前 UI 记录的已登录状态
        status_logged_in = self.lbl_qq.text() == "QQ 登录状态: 已登录"
        
        if internal_running or external_running or status_logged_in:
            self.bot_service.start()
        else:
            QMessageBox.information(self, "提示", "请先完成 QQ 扫码登录。")

    def login_qq(self):
        # 1. Start NapCat if no process is running (check QProcess state directly,
        #    bypassing is_running_internally which only returns True for "RUNNING" state
        #    and bypassing check_external_status which blocks the GUI for 2 seconds)
        process_not_running = self.napcat_service.process.state() == QProcess.ProcessState.NotRunning
        if process_not_running:
            path = self.napcat_service.settings_service.get("NAPCAT_PATH", "").strip()
            if not path:
                QMessageBox.warning(self, "错误", "请先在 'NapCat & QQ' 页面配置 NapCat.Shell 路径。")
                return
            self.napcat_service.start(path)

        # 2. Open QR dialog and keep reference
        self._qr_dialog = QQQrCodeDialog(self.qq_login_service, self.webui_service, self)
        self.qq_login_service.start_login_flow()
        self._qr_dialog.exec()

    def on_login_success(self):
        self.lbl_qq.setText("QQ 登录状态: 已登录")

    def on_login_failed(self, err):
        pass
            
    def on_login_status_updated(self, status):
        self.lbl_qq.setText(f"QQ 登录状态: {status}")

    def restart_bot(self):
        self.bot_service.restart()

    def set_logout_stop_busy(self, busy: bool):
        self.btn_stop_napcat.setEnabled(not busy)

    def update_bot_status(self, state: str):
        self.lbl_bot.setText(f"Bot Status: {state}")
        is_running = state in ["Running", "Starting"]
        self.btn_start_bot.setEnabled(not is_running)
        self.btn_stop_bot.setEnabled(is_running)
        self.btn_restart_bot.setEnabled(is_running)

    def update_napcat_status(self, state: str):
        self.lbl_napcat.setText(f"NapCat Status: {state}")
