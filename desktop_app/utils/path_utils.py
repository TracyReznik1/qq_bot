import sys
import os
from pathlib import Path
from PySide6.QtCore import QStandardPaths

def get_app_dir() -> Path:
    """Returns the directory of the running executable or script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        # Assuming path_utils.py is inside desktop_app/utils, and app_dir is the root
        return Path(__file__).parent.parent.parent.resolve()

def get_config_dir() -> Path:
    """Returns the user configuration directory (%LOCALAPPDATA%\ATRIQQBot)."""
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not base:
        base = os.path.join(os.getenv("LOCALAPPDATA", ""), "ATRIQQBot")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_data_dir(env_data_dir: str = None) -> Path:
    """Returns the user data directory, respecting user settings if provided."""
    if env_data_dir:
        path = Path(env_data_dir)
        if not path.is_absolute():
            path = get_app_dir() / path
    else:
        path = get_config_dir() / "data"
    
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_backup_dir() -> Path:
    """Returns the directory for memory backups."""
    path = get_config_dir() / "backups" / "memories"
    path.mkdir(parents=True, exist_ok=True)
    return path
