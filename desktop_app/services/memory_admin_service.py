import os
import json
import time
import shutil
from pathlib import Path
from PySide6.QtCore import QObject

from src.utils.storage import safe_id
from desktop_app.utils.path_utils import get_data_dir, get_backup_dir

class MemoryAdminService(QObject):
    def __init__(self, data_dir: str):
        super().__init__()
        self.data_dir = get_data_dir(data_dir)
        self.memory_dir = self.data_dir / "memories"
        self.backup_dir = get_backup_dir()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_memory_file_path(self, key: str) -> Path:
        return self.memory_dir / f"{safe_id(key)}.json"

    def list_memories(self) -> list[str]:
        if not self.memory_dir.exists():
            return []
        return [f.name for f in self.memory_dir.glob("*.json")]

    def load_memory(self, filename: str) -> dict:
        path = self.memory_dir / filename
        if not path.exists():
            return {"facts": []}
            
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_raw(self, filename: str) -> str:
        path = self.memory_dir / filename
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def backup_memory(self, filename: str) -> str:
        src = self.memory_dir / filename
        if not src.exists():
            return ""
            
        timestamp = int(time.time())
        backup_name = f"{src.stem}_{timestamp}.json"
        dest = self.backup_dir / backup_name
        shutil.copy2(src, dest)
        return str(dest)

    def save_memory(self, filename: str, content: dict) -> tuple[bool, str]:
        path = self.memory_dir / filename
        
        # 1. Backup if exists
        if path.exists():
            self.backup_memory(filename)
            
        # 2. Write to temp file
        temp_path = self.memory_dir / f"{filename}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
                
            # 3. Atomic replace
            os.replace(temp_path, path)
            
            # 4. Read back to verify
            self.load_memory(filename)
            return True, "Saved successfully."
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            return False, f"Save failed: {str(e)}"

    def delete_memory(self, filename: str) -> bool:
        path = self.memory_dir / filename
        if path.exists():
            self.backup_memory(filename)
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return True
