import os
from io import BytesIO
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox)
from PySide6.QtGui import QPixmap, QImageReader, QDesktopServices
from PySide6.QtCore import Qt, QUrl

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

class QQQrCodeDialog(QDialog):
    def __init__(self, login_service, webui_service, parent=None):
        super().__init__(parent)
        self.login_service = login_service
        self.webui_service = webui_service
        
        self.setWindowTitle("QQ 扫码登录")
        self.setFixedSize(400, 500)
        
        layout = QVBoxLayout(self)
        
        self.lbl_status = QLabel("正在初始化...")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(self.lbl_status)
        
        self.lbl_qr = QLabel("等待二维码...")
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setFixedSize(300, 300)
        self.lbl_qr.setStyleSheet("border: 1px solid #ccc; background-color: #fff;")
        layout.addWidget(self.lbl_qr, alignment=Qt.AlignCenter)
        
        self.lbl_instruction = QLabel("请使用手机 QQ 扫描二维码")
        self.lbl_instruction.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_instruction)
        
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新二维码")
        self.btn_refresh.clicked.connect(self.on_refresh)
        
        self.btn_webui = QPushButton("打开 NapCat WebUI")
        self.btn_webui.clicked.connect(self.on_open_webui)
        
        self.btn_cancel = QPushButton("取消登录")
        self.btn_cancel.clicked.connect(self.on_cancel)
        
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_webui)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        # Connections
        self.login_service.status_updated.connect(self.update_status)
        self.login_service.qrcode_ready.connect(self.show_qrcode)
        self.login_service.login_success.connect(self.on_login_success)
        self.login_service.login_failed.connect(self.on_login_failed)

    def update_status(self, text):
        self.lbl_status.setText(text)
        if "过期" in text:
            self.btn_refresh.setEnabled(True)
        if "失败" in text:
            # Hide QR code, show error
            self.lbl_qr.setText(text)
            self.btn_refresh.setVisible(False)
            self.btn_webui.setVisible(False)
            self.btn_cancel.setText("关闭")

    def show_qrcode(self, qr_type, data):
        if qr_type == "url":
            if not QRCODE_AVAILABLE:
                self.lbl_qr.setText("未安装 qrcode 模块，\n无法渲染 URL 二维码")
                return
            try:
                img = qrcode.make(data, box_size=10, border=2)
                buf = BytesIO()
                img.save(buf, format="PNG")
                pixmap = QPixmap()
                if not pixmap.loadFromData(buf.getvalue()):
                    self.lbl_qr.setText("二维码加载失败 (loadFromData error)")
                    return
                # Scale smoothly, but preserve sharp edges for QR
                pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.FastTransformation)
                self.lbl_qr.setPixmap(pixmap)
            except Exception as e:
                self.lbl_qr.setText(f"二维码生成异常:\n{str(e)}")
        elif qr_type == "file":
            if not os.path.exists(data):
                self.lbl_qr.setText("二维码文件不存在")
                return
            pixmap = QPixmap(data)
            if pixmap.isNull():
                self.lbl_qr.setText("无法读取二维码图片")
                return
            pixmap = pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.FastTransformation)
            self.lbl_qr.setPixmap(pixmap)
            
    def on_refresh(self):
        self.btn_refresh.setEnabled(False)
        self.login_service.refresh_qr()
        
    def on_open_webui(self):
        url = self.webui_service.base_url
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.warning(self, "警告", "WebUI 地址尚未获取，请稍候。")
            
    def on_cancel(self):
        self.login_service.cancel_login()
        self.reject()
        
    def on_login_success(self):
        self.lbl_status.setText("QQ 登录成功")
        QMessageBox.information(self, "QQ 登录", "QQ 登录成功。")
        self.accept()
        
    def on_login_failed(self, err):
        # Already handled by status update from qq_login_service
        pass
        
    def closeEvent(self, event):
        self.login_service.cancel_login()
        super().closeEvent(event)
