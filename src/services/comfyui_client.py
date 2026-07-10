"""ComfyUI API client for remote prompt execution and image retrieval.

Uses the ComfyUI REST API:  ``POST /prompt`` → poll ``GET /history/{prompt_id}``
→ ``GET /view`` to download outputs.

WebSocket support is reserved for a future iteration.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("qq-bot")


@dataclass(frozen=True)
class GeneratedImage:
    path: str       # absolute local path
    filename: str   # original filename from ComfyUI
    prompt_id: str


# ── module-level helpers ────────────────────────────────────────────────

def _safe_error_preview(response) -> str:
    """Return the first 1000 chars of the response body for logging."""
    try:
        text = response.text
        return (text or "")[:1000]
    except Exception:
        return "<unreadable>"


def _sanitize_prompt_for_comfyui(workflow: dict) -> dict:
    """Return a copy of *workflow* containing only real ComfyUI nodes.

    A real node is a ``dict`` with both ``"class_type"`` and ``"inputs"``
    keys.  Entries like ``"client_id"``, ``"metadata"``, or stray strings
    are silently dropped — ComfyUI rejects non-node keys inside the
    ``"prompt"`` object with HTTP 500.
    """
    sanitized: dict[str, Any] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        if "class_type" not in node or "inputs" not in node:
            continue
        sanitized[str(node_id)] = node
    return sanitized


# ── ComfyUI client ─────────────────────────────────────────────────────

class ComfyUIClient:
    """Thin wrapper around the ComfyUI REST API."""

    def __init__(self, base_url: str, timeout_seconds: int, client_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client_id = client_id

    # ── public ────────────────────────────────────────────────────────

    def generate(self, workflow: dict, output_dir: str) -> list[GeneratedImage]:
        """Submit *workflow* and wait for completion, then download outputs.

        Raises ``RuntimeError`` when ComfyUI is unreachable, times out, or
        produces no output images.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        prompt_id = self._queue_prompt(workflow)
        outputs = self._wait_for_outputs(prompt_id)

        if not outputs:
            raise RuntimeError(
                "ComfyUI finished but produced no output images. "
                "Check the workflow configuration."
            )

        images: list[GeneratedImage] = []
        for output_info in outputs:
            filename = output_info["filename"]
            subfolder = output_info.get("subfolder", "")
            folder_type = output_info.get("type", "output")

            image_data = self._download_image(filename, subfolder, folder_type)
            safe_name = f"{uuid.uuid4().hex}_{filename}"
            dest = out_dir / safe_name
            dest.write_bytes(image_data)
            images.append(
                GeneratedImage(
                    path=str(dest.resolve()),
                    filename=filename,
                    prompt_id=prompt_id,
                )
            )

        return images

    # ── private helpers ───────────────────────────────────────────────

    def _queue_prompt(self, workflow: dict) -> str:
        sanitized = _sanitize_prompt_for_comfyui(workflow)
        payload: dict[str, Any] = {
            "prompt": sanitized,
            "client_id": self._client_id,
        }
        try:
            resp = requests.post(
                f"{self._base_url}/prompt",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
        except requests.ConnectionError:
            raise RuntimeError("ComfyUI 没有响应。请先启动 ComfyUI Desktop。")
        except requests.Timeout:
            raise RuntimeError("ComfyUI 连接超时，请检查 ComfyUI 是否正常运行。")
        except requests.HTTPError as exc:
            status = exc.response.status_code
            preview = _safe_error_preview(exc.response)
            sanitized_2 = _sanitize_prompt_for_comfyui(workflow)
            node_ids = list(sanitized_2.keys())
            logger.error(
                "ComfyUI request failed endpoint=/prompt status=%s "
                "response_preview=%s prompt_nodes=%s node_ids=%s",
                status, preview, len(node_ids), node_ids[:30],
            )
            raise RuntimeError(
                f"ComfyUI 返回错误 (HTTP {status})，请检查工作流配置。"
            )

        data = resp.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI 未返回 prompt_id，请检查工作流是否有效。")
        return str(prompt_id)

    def _wait_for_outputs(self, prompt_id: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + self._timeout
        poll_interval = 2.0

        while time.monotonic() < deadline:
            try:
                resp = requests.get(
                    f"{self._base_url}/history/{prompt_id}",
                    timeout=10,
                )
                resp.raise_for_status()
            except requests.ConnectionError:
                raise RuntimeError("ComfyUI 连接丢失，请检查 ComfyUI 是否仍在运行。")
            except requests.Timeout:
                logger.debug("ComfyUI history poll timed out, retrying...")
                time.sleep(poll_interval)
                continue

            history = resp.json()
            entry = history.get(prompt_id)
            if entry is not None:
                outputs = entry.get("outputs") or {}
                all_images: list[dict[str, Any]] = []
                for _node_id, node_output in outputs.items():
                    images = node_output.get("images") or []
                    if not isinstance(images, list):
                        continue
                    for img in images:
                        if isinstance(img, dict):
                            all_images.append(dict(img))
                if all_images:
                    return all_images

            time.sleep(poll_interval)

        raise RuntimeError(
            f"ComfyUI 执行超时（{self._timeout} 秒）。"
            "请检查工作流是否有死循环，或调大 COMFYUI_TIMEOUT_SECONDS。"
        )

    def _download_image(
        self, filename: str, subfolder: str, folder_type: str
    ) -> bytes:
        params: dict[str, str] = {"filename": filename}
        if subfolder:
            params["subfolder"] = subfolder
        if folder_type:
            params["type"] = folder_type

        try:
            resp = requests.get(
                f"{self._base_url}/view",
                params=params,
                timeout=60,
            )
            resp.raise_for_status()
        except requests.ConnectionError:
            raise RuntimeError("ComfyUI 连接丢失，无法下载生成图片。")
        except requests.Timeout:
            raise RuntimeError("ComfyUI 图片下载超时。")

        content_type = (resp.headers.get("Content-Type") or "").lower()
        allowed = {"image/png", "image/jpeg", "image/webp"}
        if not any(content_type.startswith(ct) for ct in allowed):
            raise RuntimeError(
                f"ComfyUI 返回了非图片内容 ({content_type})，无法保存。"
            )

        return resp.content
