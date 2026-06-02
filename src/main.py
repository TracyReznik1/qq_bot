import hmac
import logging
import time
from typing import Any

from flask import Flask, request

from src.chat.chat_service import generate_reply
from src.chat.memory import migrate_legacy_memory_files
from src.commands import CommandContext, handle_command
from src.config import config
from src.messaging import (
    MessageQueue,
    enqueue_message,
    get_event_session_key,
    mark_message_seen,
)
from src.router import route_message
from src.services.onebot_client import OneBotClient


app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("qq-bot")

MAX_PROCESSED_MESSAGE_IDS = 500
_startup_initialized = False

onebot = OneBotClient(config)

message_queue = MessageQueue(
    max_workers=4,
    max_processed_message_ids=MAX_PROCESSED_MESSAGE_IDS,
)


def startup() -> None:
    global _startup_initialized
    if _startup_initialized:
        return

    migrate_legacy_memory_files()
    _startup_initialized = True


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
                CommandContext(uid=uid, session_key=get_event_session_key(data) or "", raw_message=raw_msg),
            )
            if result.handled and result.reply:
                send_reply(target_id, result.reply, is_group)
            return

        reply = generate_reply(get_event_session_key(data) or "", raw_msg)
        send_reply(target_id, reply, is_group)
    except RuntimeError as error:
        logger.exception("Configuration error")
        send_reply(target_id, f"配置还没好：{error}", is_group)
    except Exception:
        logger.exception("Message handling failed")
        send_reply(target_id, "我这边处理失败了，先缓一缓再试。", is_group)


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


@app.route("/", methods=["POST"])
def onebot_event() -> dict[str, str] | tuple[dict[str, str], int]:
    if not is_callback_authorized():
        return {"status": "forbidden"}, 403

    data = request.get_json(silent=True) or {}
    if data.get("post_type") == "message" and mark_message_seen(data, message_queue):
        enqueue_message(data, message_queue, process_message_safely)
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
