import json
import os
from pathlib import Path
from dotenv import dotenv_values

from desktop_app.services.secret_service import SecretService
from desktop_app.utils.path_utils import get_config_dir

SETTINGS_FILENAME = "settings.json"
SENSITIVE_KEYS = {
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "ONEBOT_ACCESS_TOKEN",
    "CALLBACK_SECRET"
}

class SettingsService:
    def __init__(self):
        self.config_dir = get_config_dir()
        self.settings_file = self.config_dir / SETTINGS_FILENAME
        self._cache = {}
        self.load()

    def load(self):
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}
        else:
            self._cache = {}

    def save(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def get(self, key: str, default=None):
        return self._cache.get(key, default)

    def set(self, key: str, value):
        self._cache[key] = value
        self.save()

    def get_all(self):
        return dict(self._cache)

    def import_from_env(self, env_path: str) -> tuple[int, int]:
        """Import settings from .env file. Returns (normal_count, secret_count)"""
        path = Path(env_path)
        if not path.exists():
            return 0, 0
        
        values = dotenv_values(path)
        normal_count = 0
        secret_count = 0
        
        for k, v in values.items():
            if v is None:
                continue
            if k in SENSITIVE_KEYS:
                SecretService.set_secret(k, v)
                secret_count += 1
            else:
                self._cache[k] = v
                normal_count += 1
                
        if normal_count > 0:
            self.save()
            
        return normal_count, secret_count
