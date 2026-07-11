import sys
from PySide6.QtWidgets import QApplication

from desktop_app.services.settings_service import SettingsService
from desktop_app.services.bot_process_service import BotProcessService
from desktop_app.services.napcat_service import NapCatService
from desktop_app.services.memory_admin_service import MemoryAdminService
from desktop_app.services.diagnostics_service import DiagnosticsService
from desktop_app.main_window import MainWindow

def run_gui() -> int:
    app = QApplication(sys.argv)
    
    settings_service = SettingsService()
    bot_service = BotProcessService(settings_service)
    napcat_service = NapCatService(settings_service)
    
    data_dir = settings_service.get("DATA_DIR", "atri_data")
    memory_service = MemoryAdminService(data_dir)
    
    diagnostics_service = DiagnosticsService(
        settings_service, bot_service, memory_service, napcat_service
    )
    
    from desktop_app.services.napcat_webui_service import NapCatWebUIService
    from desktop_app.services.qq_login_service import QQLoginService
    
    webui_service = NapCatWebUIService()
    qq_login_service = QQLoginService(napcat_service, webui_service)
    
    services = {
        'settings': settings_service,
        'bot': bot_service,
        'napcat': napcat_service,
        'memory': memory_service,
        'diagnostics': diagnostics_service,
        'webui': webui_service,
        'qq_login': qq_login_service
    }
    
    window = MainWindow(services)
    window.show()
    
    return app.exec()
