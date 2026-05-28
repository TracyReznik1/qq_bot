import hmac
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import requests
from flask import Flask, request

from src.chat.chat_service import generate_reply
from src.chat.memory import migrate_legacy_memory_files
from src.commands import CommandContext, handle_command
from src.config import Config, config
from src.router import route_message
from src.utils.storage import safe_id


app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("qq-bot")

message_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qq-message")
processed_message_ids: set[str] = set()
processed_message_order: deque[str] = deque()
processed_message_lock = Lock()
session_queue_lock = Lock()
session_message_queues: dict[str, deque[dict[str, Any]]] = {}
active_session_workers: set[str] = set()
MAX_PROCESSED_MESSAGE_IDS = 500
_startup_initialized = False


def startup() -> None:
    global _startup_initialized
    if _startup_initialized:
        return

    migrate_legacy_memory_files()
    _startup_initialized = True


def build_session_key(uid: str, data: dict[str, Any], is_group: bool) -> str:
    if is_group:
        return f"group:{safe_id(data.get('group_id'))}:{safe_id(uid)}"
    return f"private:{safe_id(uid)}"


def get_event_session_key(data: dict[str, Any]) -> str | None:
    uid = str(data.get("user_id", ""))
    raw_msg = str(data.get("raw_message", "")).strip()
    if not uid or not raw_msg:
        return None

    is_group = data.get("message_type") == "group"
    return build_session_key(uid, data, is_group)


def build_message_dedupe_key(data: dict[str, Any], message_id: Any) -> str:
    message_type = str(data.get("message_type") or "unknown")
    if message_type == "group":
        scope_kind = "group"
        scope_id = data.get("group_id")
    else:
        scope_kind = "user"
        scope_id = data.get("user_id")

    return ":".join(
        [
            safe_id(data.get("self_id")),
            safe_id(message_type),
            scope_kind,
            safe_id(scope_id),
            safe_id(message_id),
        ]
    )


class OneBotClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.onebot_access_token:
            headers["Authorization"] = f"Bearer {self.cfg.onebot_access_token}"
        return headers

    def send_msg(self, target_id: Any, message: str, is_group: bool = False) -> None:
        message = (message or "").strip()
        if not message:
            return

        endpoint = "send_group_msg" if is_group else "send_private_msg"
        payload_key = "group_id" if is_group else "user_id"
        payload = {payload_key: target_id, "message": message}
        try:
            response = requests.post(
                f"{self.cfg.onebot_url}/{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self.cfg.request_timeout,
            )
            response.raise_for_status()
        except Exception:
            logger.exception("Failed to send QQ message")


onebot = OneBotClient(config)


def strip_bot_mention(raw_msg: str, self_id: str) -> tuple[bool, str]:
    at_me = f"[CQ:at,qq={self_id}]"
    if at_me in raw_msg:
        return True, raw_msg.replace(at_me, "").strip()
    return False, raw_msg.strip()


def split_reply(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    limit = max(config.max_reply_chars, 200)
    parts = []
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind("。", 0, limit), text.rfind("，", 0, limit))
        if cut < limit // 2:
            parts.append(text[:limit].strip())
            text = text[limit:].strip()
        else:
            parts.append(text[: cut + 1].strip())
            text = text[cut + 1 :].strip()
    if text:
        parts.append(text)
    return parts


def send_reply(target_id: Any, text: str, is_group: bool) -> None:
    for part in split_reply(text):
        onebot.send_msg(target_id, part, is_group=is_group)
        time.sleep(0.2)


def process_message(data: dict[str, Any]) -> None:
    uid = str(data.get("user_id", ""))
    raw_msg = str(data.get("raw_message", "")).strip()
    if not uid or not raw_msg:
        return

    is_group = data.get("message_type") == "group"
    self_id = str(data.get("self_id", ""))
    target_id = data.get("group_id") if is_group else uid
    session_key = build_session_key(uid, data, is_group)

    if is_group and config.require_group_at:
        mentioned, raw_msg = strip_bot_mention(raw_msg, self_id)
        if not mentioned:
            return
        if not raw_msg:
            return

    try:
        route = route_message(raw_msg)
        if route.handler == "command":
            result = handle_command(
                route,
                CommandContext(uid=uid, session_key=session_key, raw_message=raw_msg),
            )
            if result.handled and result.reply:
                send_reply(target_id, result.reply, is_group)
            return

        reply = generate_reply(session_key, raw_msg)
        send_reply(target_id, reply, is_group)
    except RuntimeError as error:
        logger.exception("Configuration error")
        send_reply(target_id, f"配置还没好：{error}", is_group)
    except Exception:
        logger.exception("Message handling failed")
        send_reply(target_id, "我这边处理失败了，先缓一缓再试。", is_group)


def mark_message_seen(data: dict[str, Any]) -> bool:
    message_id = data.get("message_id")
    if message_id is None:
        return True

    key = build_message_dedupe_key(data, message_id)
    with processed_message_lock:
        if key in processed_message_ids:
            return False

        processed_message_ids.add(key)
        processed_message_order.append(key)
        while len(processed_message_order) > MAX_PROCESSED_MESSAGE_IDS:
            old_key = processed_message_order.popleft()
            processed_message_ids.discard(old_key)
        return True


def process_message_safely(data: dict[str, Any]) -> None:
    try:
        process_message(data)
    except Exception:
        logger.exception("Background message processing failed")


def is_callback_authorized() -> bool:
    secret = config.callback_secret.strip()
    if not secret:
        return True

    authorization = request.headers.get("Authorization", "").strip()
    callback_secret = request.headers.get("X-ATRI-Callback-Secret", "").strip()
    return hmac.compare_digest(authorization, f"Bearer {secret}") or hmac.compare_digest(
        callback_secret, secret
    )


def drain_session_queue(session_key: str) -> None:
    while True:
        with session_queue_lock:
            queue = session_message_queues.get(session_key)
            if not queue:
                session_message_queues.pop(session_key, None)
                active_session_workers.discard(session_key)
                return
            data = queue.popleft()

        process_message_safely(data)


def enqueue_message(data: dict[str, Any]) -> None:
    session_key = get_event_session_key(data)
    if session_key is None:
        return

    should_start_worker = False
    with session_queue_lock:
        queue = session_message_queues.setdefault(session_key, deque())
        queue.append(data)
        if session_key not in active_session_workers:
            active_session_workers.add(session_key)
            should_start_worker = True

    if should_start_worker:
        message_executor.submit(drain_session_queue, session_key)


@app.route("/", methods=["POST"])
def onebot_event() -> dict[str, str] | tuple[dict[str, str], int]:
    if not is_callback_authorized():
        return {"status": "forbidden"}, 403

    data = request.get_json(silent=True) or {}
    if data.get("post_type") == "message" and mark_message_seen(data):
        enqueue_message(data)
    return {"status": "ok"}


@app.route("/health", methods=["GET"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "bot_name": config.bot_name,
        "deepseek_configured": bool(config.deepseek_api_key),
        "onebot_url": config.onebot_url,
        "require_group_at": config.require_group_at,
    }


def run() -> None:
    startup()
    logger.info("Starting %s on %s:%s", config.bot_name, config.host, config.port)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    run()
