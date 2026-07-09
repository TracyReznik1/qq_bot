"""OneBot HTTP API client — message and image sending with base64 fallback."""

import base64
import logging
from pathlib import Path
from typing import Any

import requests

from src.config import Config

logger = logging.getLogger("qq-bot")

# Recognised image MIME types for base64 tagging.
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _guess_mime(path: Path) -> str:
    return _IMAGE_MIME.get(path.suffix.lower(), "image/jpeg")


def build_cq_image_file(image_path: str) -> str:
    """Build a ``[CQ:image,file=file:///...]`` CQ code."""
    resolved = Path(image_path).resolve()
    return f"[CQ:image,file={resolved.as_uri()}]"


def build_cq_image_base64(image_path: str) -> str:
    """Build a ``[CQ:image,file=base64://...]`` CQ code.

    Logs *size only* — never the base64 content.
    """
    resolved = Path(image_path).resolve()
    data = resolved.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    mime = _guess_mime(resolved)
    logger.info(
        "OneBot base64 image built path=%s size_bytes=%s base64_len=%s",
        resolved.name,
        len(data),
        len(b64),
    )
    return f"[CQ:image,file=base64://{b64},{mime}]"


class OneBotClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.onebot_access_token:
            headers["Authorization"] = f"Bearer {self.cfg.onebot_access_token}"
        return headers

    # ── text messages ─────────────────────────────────────────────────

    def send_msg(self, target_id: Any, message: str, is_group: bool = False) -> None:
        message = (message or "").strip()
        if not message:
            logger.info("OneBot send skipped: empty message target_id=%s is_group=%s", target_id, is_group)
            return

        endpoint = "send_group_msg" if is_group else "send_private_msg"
        payload_key = "group_id" if is_group else "user_id"
        payload = {payload_key: target_id, "message": message}
        try:
            logger.info(
                "OneBot send request endpoint=%s target_id=%s is_group=%s chars=%s",
                endpoint,
                target_id,
                is_group,
                len(message),
            )
            response = requests.post(
                f"{self.cfg.onebot_url}/{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self.cfg.request_timeout,
            )
            response.raise_for_status()
            logger.info(
                "OneBot send success endpoint=%s target_id=%s is_group=%s status_code=%s",
                endpoint,
                target_id,
                is_group,
                response.status_code,
            )
        except Exception:
            logger.exception(
                "OneBot send failed endpoint=%s target_id=%s is_group=%s chars=%s",
                endpoint,
                target_id,
                is_group,
                len(message),
            )

    # ── image sending with base64 fallback ─────────────────────────────

    def _send_msg_and_catch(self, target_id: Any, message: str, is_group: bool) -> bool:
        """Return True on success, False on any error (logged internally)."""
        message = (message or "").strip()
        if not message:
            return False

        endpoint = "send_group_msg" if is_group else "send_private_msg"
        payload_key = "group_id" if is_group else "user_id"
        payload = {payload_key: target_id, "message": message}
        try:
            resp = requests.post(
                f"{self.cfg.onebot_url}/{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self.cfg.request_timeout,
            )
            resp.raise_for_status()
            return True
        except Exception:
            logger.debug("OneBot image send attempt failed — will fallback if available", exc_info=True)
            return False

    def send_image(self, target_id: Any, image_path: str, is_group: bool = False) -> bool:
        """Send an image via OneBot with automatic fallback.

        Strategy
        --------
        1.  If the file doesn't exist → log warning, return ``False``.
        2.  Try ``file:///`` CQ code first.
        3.  On success → return ``True``.
        4.  On failure → if ``image_send_base64_fallback`` is enabled and the
            file is under ``image_send_base64_max_mb``, build a ``base64://``
            CQ code and retry.
        5.  Return ``True``/``False``.

        Notes
        -----
        - Old callers that used ``send_image()`` without expecting a return
          value are unaffected (the return is only informational).
        - Logging never includes the raw base64 payload.
        """
        resolved = Path(image_path).resolve()
        if not resolved.exists():
            logger.warning("OneBot image send skipped: file not found path=%s", resolved)
            return False

        # 1. Try file:/// first
        file_msg = build_cq_image_file(str(resolved))
        logger.info(
            "OneBot image send (file URI) target_id=%s is_group=%s path=%s size_bytes=%s",
            target_id,
            is_group,
            resolved.name,
            resolved.stat().st_size,
        )
        if self._send_msg_and_catch(target_id, file_msg, is_group):
            logger.info("OneBot image send (file URI) succeeded")
            return True

        # 2. file:/// failed — try base64 fallback if enabled
        if not self.cfg.image_send_base64_fallback:
            logger.warning(
                "OneBot image send (file URI) failed and base64 fallback is disabled "
                "— image not sent path=%s",
                resolved.name,
            )
            return False

        file_size_mb = resolved.stat().st_size / (1024 * 1024)
        max_mb = self.cfg.image_send_base64_max_mb
        if file_size_mb > max_mb:
            logger.warning(
                "OneBot image send (file URI) failed and file too large for base64 "
                "fallback path=%s size_mb=%.1f max_mb=%s",
                resolved.name,
                file_size_mb,
                max_mb,
            )
            return False

        logger.info(
            "OneBot image send (file URI) failed — trying base64 fallback path=%s size_mb=%.1f",
            resolved.name,
            file_size_mb,
        )
        b64_msg = build_cq_image_base64(str(resolved))
        success = self._send_msg_and_catch(target_id, b64_msg, is_group)
        if success:
            logger.info("OneBot image send (base64 fallback) succeeded")
        else:
            logger.warning("OneBot image send (base64 fallback) also failed")
        return success

    # ── legacy (kept for existing callers) ───────────────────────────

    def send_image_file_only(self, target_id: Any, image_path: str, is_group: bool = False) -> None:
        """Send an image via CQ image ``file://`` URI — no fallback.

        Kept for callers that want the old file-only behaviour without
        automatic base64 retry.
        """
        resolved = Path(image_path).resolve()
        if not resolved.exists():
            logger.warning(
                "OneBot image send skipped: file not found path=%s", resolved
            )
            return
        uri = resolved.as_uri()
        message = f"[CQ:image,file={uri}]"
        self.send_msg(target_id, message, is_group=is_group)
