import os
import json
import urllib.request
import urllib.error
from PySide6.QtCore import QObject, Signal, QThread

from desktop_app.services.secret_service import SecretService

class DiagnosticWorker(QThread):
    result_ready = Signal(dict)
    
    def __init__(self, settings_service, bot_service, memory_service, napcat_service):
        super().__init__()
        self.settings_service = settings_service
        self.bot_service = bot_service
        self.memory_service = memory_service
        self.napcat_service = napcat_service

    def run(self):
        results = {}
        
        # 1. API Keys
        results["Gemini API Key"] = "Configured" if SecretService.get_secret("GEMINI_API_KEY") else "Missing"
        results["DeepSeek API Key"] = "Configured" if SecretService.get_secret("DEEPSEEK_API_KEY") else "Missing"
        results["OneBot Access Token"] = "Configured" if SecretService.get_secret("ONEBOT_ACCESS_TOKEN") else "Missing"
        
        # 2. Permissions
        data_dir = self.memory_service.data_dir
        results["Data Directory Writable"] = "Yes" if os.access(data_dir, os.W_OK) else "No"
        
        # 3. Bot Process
        results["Bot Process"] = "Running" if self.bot_service.is_running() else "Stopped"
        
        # 4. Bot /health endpoint (if running)
        if self.bot_service.is_running():
            host = self.settings_service.get("BOT_HOST", "127.0.0.1")
            port = self.settings_service.get("BOT_PORT", "5000")
            try:
                req = urllib.request.Request(f"http://{host}:{port}/health")
                with urllib.request.urlopen(req, timeout=2) as response:
                    results["Bot HTTP /health"] = "OK" if response.status == 200 else f"Error: {response.status}"
            except Exception as e:
                results["Bot HTTP /health"] = f"Unreachable: {str(e)}"
        else:
            results["Bot HTTP /health"] = "N/A (Stopped)"
            
        # 5. NapCat Status
        results["NapCat"] = self.napcat_service.check_external_status()
        
        # 6. Memory Valid
        invalid_count = 0
        for f in self.memory_service.list_memories():
            try:
                self.memory_service.load_memory(f)
            except Exception:
                invalid_count += 1
        results["Memory Files"] = "All Valid" if invalid_count == 0 else f"{invalid_count} Invalid"
        
        # 7. ComfyUI
        if self.settings_service.get("IMAGE_ENABLE", "false").lower() == "true":
            comfy_url = self.settings_service.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
            try:
                req = urllib.request.Request(f"{comfy_url}/system_stats")
                with urllib.request.urlopen(req, timeout=2) as response:
                    results["ComfyUI"] = "Reachable" if response.status == 200 else f"Error: {response.status}"
            except Exception as e:
                results["ComfyUI"] = f"Unreachable: {str(e)}"
        else:
            results["ComfyUI"] = "Disabled"
            
        self.result_ready.emit(results)

class DiagnosticsService(QObject):
    def __init__(self, settings_service, bot_service, memory_service, napcat_service):
        super().__init__()
        self.settings_service = settings_service
        self.bot_service = bot_service
        self.memory_service = memory_service
        self.napcat_service = napcat_service
        self.worker = None

    def run_diagnostics(self, callback):
        if self.worker and self.worker.isRunning():
            return
            
        self.worker = DiagnosticWorker(
            self.settings_service, self.bot_service, self.memory_service, self.napcat_service
        )
        self.worker.result_ready.connect(callback)
        self.worker.start()
