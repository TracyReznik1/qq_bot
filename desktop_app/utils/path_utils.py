import sys
import os
from pathlib import Path
from PySide6.QtCore import QStandardPaths, QCoreApplication

def is_packaged_runtime() -> bool:
    """Returns True if running in a packaged environment (Nuitka or PyInstaller)."""
    # PyInstaller
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return True
    
    # Nuitka compiled
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "__compiled__"):
        return True

    # Fallback: if sys.executable is not python.exe/pythonw.exe
    exe_name = Path(sys.executable).name.lower()
    if exe_name not in ["python.exe", "pythonw.exe"] and exe_name.endswith(".exe"):
        return True

    return False

def build_core_process_command() -> tuple[str, list[str]]:
    """Builds the correct program and arguments to launch the Bot core."""
    if is_packaged_runtime():
        app_path = QCoreApplication.applicationFilePath()
        if not app_path:
            app_path = sys.executable
        return (app_path, ["--core"])
    else:
        app_dir = Path(__file__).parent.parent.parent.resolve()
        launcher_path = app_dir / "launcher.py"
        return (sys.executable, [str(launcher_path), "--core"])

def get_app_dir() -> Path:
    """Returns the directory of the running executable or script."""
    if is_packaged_runtime():
        app_path = QCoreApplication.applicationFilePath()
        if app_path:
            return Path(app_path).parent
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
