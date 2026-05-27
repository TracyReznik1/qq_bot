import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_csv_set(name: str) -> frozenset[str]:
    value = os.getenv(name, "")
    items = [item.strip() for item in value.replace(";", ",").split(",")]
    return frozenset(item for item in items if item)


def resolve_path(value: str, default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


@dataclass(frozen=True)
class Config:
    bot_name: str = os.getenv("BOT_NAME", "ATRI")
    bot_persona: str = os.getenv(
        "BOT_PERSONA",
        "你是 ATRI，一个 QQ 聊天机器人。说话自然、可爱、有一点吐槽感，但要友好、简洁、靠谱。",
    )
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_url: str = os.getenv(
        "DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"
    )
    onebot_url: str = os.getenv("ONEBOT_API_URL", "http://127.0.0.1:3000").rstrip("/")
    onebot_access_token: str = os.getenv("ONEBOT_ACCESS_TOKEN", "")
    callback_secret: str = os.getenv("CALLBACK_SECRET", "")
    proxy_url: str = os.getenv("PROXY_URL", "")
    host: str = os.getenv("BOT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port: int = env_int("BOT_PORT", 5000)
    require_group_at: bool = env_bool("REQUIRE_GROUP_AT", True)
    admin_qq_ids: frozenset[str] = env_csv_set("ADMIN_QQ_IDS")
    data_dir: Path = resolve_path(os.getenv("DATA_DIR", ""), "atri_data")
    search_max_results: int = env_int("SEARCH_MAX_RESULTS", 4)
    history_turns: int = env_int("HISTORY_TURNS", 8)
    memory_limit: int = env_int("MEMORY_LIMIT", 30)
    request_timeout: float = env_float("REQUEST_TIMEOUT", 18.0)
    max_reply_chars: int = env_int("MAX_REPLY_CHARS", 1700)

    @property
    def proxies(self) -> dict[str, str] | None:
        if not self.proxy_url:
            return None
        return {"http": self.proxy_url, "https": self.proxy_url}


config = Config()
