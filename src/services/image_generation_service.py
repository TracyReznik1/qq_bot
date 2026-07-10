"""Workflow loading, patching, LoRA control, and image generation orchestrator.

Ties together prompt conversion, ComfyUI API calls, task locking, and the
onebot image send path.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import threading
from pathlib import Path
from typing import Any

from src.config import config
from src.services.comfyui_client import ComfyUIClient, GeneratedImage
from src.services.image_prompt_service import build_prompt_spec, ImagePromptSpec

logger = logging.getLogger("qq-bot")

IMAGE_GENERATION_LOCK = threading.Lock()


class WorkflowPatchError(Exception):
    """Raised when a required node cannot be located in the workflow."""


# ── workflow loading ────────────────────────────────────────────────────

def load_workflow(path: str) -> dict:
    """Load a ComfyUI API workflow JSON from *path*.

    Uses ``utf-8-sig`` to tolerate UTF-8 BOM — some ComfyUI workflow
    files exported from the desktop editor include a leading BOM.

    ComfyUI API format wraps nodes inside a ``"prompt"`` key::
        {"prompt": {"1": {...}, "2": {...}}, "client_id": "..."}

    This function unwraps the inner ``prompt`` dict (keeping
    ``client_id``) so the patcher receives a flat node dict.  If there
    is no ``"prompt"`` key the data is returned as-is (backward
    compatible with flat test mocks).
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise WorkflowPatchError(f"工作流文件未找到：{path}")
    except json.JSONDecodeError as exc:
        raise WorkflowPatchError(f"工作流 JSON 解析失败：{exc}")

    return _unwrap_api_workflow(data)


def _unwrap_api_workflow(data: dict) -> dict:
    """Return the inner ``prompt`` dict if the loaded JSON uses the
    standard ComfyUI API wrapper::

        {"prompt": {"1": {...}}, "client_id": "..."}

    When no ``"prompt"`` key is present the original dict is returned
    unchanged.  In either case the caller receives a **new** dict so the
    original parse result is never mutated.

    Top-level ``client_id`` is **not** copied into the returned dict —
    the ComfyUI client supplies its own ``COMFYUI_CLIENT_ID`` at queue
    time and workflow-internal non-node keys would cause HTTP 500.
    """
    if not isinstance(data, dict):
        return data
    prompt = data.get("prompt")
    if not isinstance(prompt, dict):
        return data
    return dict(prompt)


# ── workflow patching ───────────────────────────────────────────────────

def _find_node_by_title(
    workflow: dict, keyword: str
) -> tuple[str, dict] | None:
    """Search nodes whose ``_meta.title`` contains *keyword* (case-insensitive)."""
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        if not isinstance(node, dict):
            continue
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        title = str(meta.get("title", "")).lower()
        if keyword.lower() in title:
            return node_id, node
    return None


def _find_node_by_class_type(
    workflow: dict, keyword: str
) -> list[tuple[str, dict]]:
    """Search nodes whose ``class_type`` contains *keyword* (case-insensitive)."""
    matches: list[tuple[str, dict]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", "")).lower()
        if keyword.lower() in ct:
            matches.append((node_id, node))
    return matches


def _find_positive_node(
    workflow: dict,
) -> tuple[str, dict]:
    if config.comfyui_positive_node_id:
        nid = config.comfyui_positive_node_id
        node = workflow.get(nid)
        if isinstance(node, dict):
            return nid, node
    # Auto-detect: CLIPTextEncode with "positive" in title or positive-like text
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        if ct != "CLIPTextEncode":
            continue
        inputs = node.get("inputs", {})
        text = str(inputs.get("text", "")).lower()
        if "positive" in text or "masterpiece" in text or "score_7" in text:
            return node_id, node
    raise WorkflowPatchError(
        "找不到正向提示词节点。请在 .env 中配置 COMFYUI_POSITIVE_NODE_ID。"
    )


def _find_negative_node(workflow: dict) -> tuple[str, dict]:
    if config.comfyui_negative_node_id:
        nid = config.comfyui_negative_node_id
        node = workflow.get(nid)
        if isinstance(node, dict):
            return nid, node
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        ct = str(node.get("class_type", ""))
        if ct != "CLIPTextEncode":
            continue
        inputs = node.get("inputs", {})
        text = str(inputs.get("text", "")).lower()
        if "worst quality" in text or "bad hands" in text or "negative" in text:
            return node_id, node
    raise WorkflowPatchError(
        "找不到负向提示词节点。请在 .env 中配置 COMFYUI_NEGATIVE_NODE_ID。"
    )


def _find_lora_nodes(workflow: dict) -> list[tuple[str, dict]]:
    return _find_node_by_class_type(workflow, "Lora")


def _find_seed_node(workflow: dict) -> tuple[str, dict] | None:
    if config.comfyui_seed_node_id:
        nid = config.comfyui_seed_node_id
        node = workflow.get(nid)
        if isinstance(node, dict):
            return nid, node
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        inputs = node.get("inputs", {})
        if "seed" in inputs and "steps" in inputs:
            return node_id, node
    return None


def _find_dimensions_node(workflow: dict) -> tuple[str, dict] | None:
    if config.comfyui_width_node_id or config.comfyui_height_node_id:
        nid = config.comfyui_width_node_id or config.comfyui_height_node_id
        node = workflow.get(nid)
        if isinstance(node, dict):
            return nid, node
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        inputs = node.get("inputs", {})
        if "width" in inputs and "height" in inputs:
            return node_id, node
    return None


def _find_save_prefix_node(workflow: dict) -> tuple[str, dict] | None:
    if config.comfyui_save_prefix_node_id:
        nid = config.comfyui_save_prefix_node_id
        node = workflow.get(nid)
        if isinstance(node, dict):
            return nid, node
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        inputs = node.get("inputs", {})
        if "filename_prefix" in inputs:
            return node_id, node
    return None


def patch_workflow(
    workflow: dict,
    spec: ImagePromptSpec,
    cfg: Any = None,
) -> dict:
    """Return a deep-copied workflow patched with *spec*.

    Does NOT mutate the original dict.
    """
    if cfg is None:
        cfg = config
    wf = copy.deepcopy(workflow)

    # Positive prompt
    pos_id, pos_node = _find_positive_node(wf)
    pos_node["inputs"]["text"] = spec.positive_prompt

    # Negative prompt
    neg_id, neg_node = _find_negative_node(wf)
    neg_node["inputs"]["text"] = spec.negative_prompt

    # Seed
    seed_node = _find_seed_node(wf)
    if seed_node is not None:
        seed = spec.seed if spec.seed is not None else random.randint(1, 2**31 - 1)
        seed_node[1]["inputs"]["seed"] = seed

    # Width / height
    dim_node = _find_dimensions_node(wf)
    if dim_node is not None:
        dim_node[1]["inputs"]["width"] = spec.width
        dim_node[1]["inputs"]["height"] = spec.height

    # Save prefix
    save_node = _find_save_prefix_node(wf)
    if save_node is not None:
        save_node[1]["inputs"]["filename_prefix"] = "atri_anima"

    # ── LoRA nodes ──────────────────────────────────────────────────
    lora_nodes = _find_lora_nodes(wf)
    if len(lora_nodes) >= 2:
        char_node = lora_nodes[0]
        style_node = lora_nodes[1]
    elif len(lora_nodes) == 1:
        char_node = lora_nodes[0]
        style_node = None
    else:
        char_node = None
        style_node = None

    # Character LoRA
    if char_node is not None:
        if cfg.image_use_character_lora and cfg.image_character_lora_name:
            char_node[1]["inputs"]["lora_name"] = cfg.image_character_lora_name
            char_node[1]["inputs"]["strength_model"] = cfg.image_character_lora_strength
        else:
            char_node[1]["inputs"]["strength_model"] = 0.0

    # Style LoRA
    if style_node is not None:
        if cfg.image_use_style_lora and cfg.image_style_lora_name:
            style_node[1]["inputs"]["lora_name"] = cfg.image_style_lora_name
            style_node[1]["inputs"]["strength_model"] = cfg.image_style_lora_strength
        else:
            style_node[1]["inputs"]["strength_model"] = 0.0

    # Client ID
    wf["client_id"] = cfg.comfyui_client_id

    return wf


# ── orchestrator ────────────────────────────────────────────────────────

def _resolve_output_dir() -> str:
    d = config.image_output_dir
    if not Path(d).is_absolute():
        d = str(Path(__file__).resolve().parents[2] / d)
    return d


def generate_image_from_text(user_text: str) -> list[GeneratedImage]:
    """Full pipeline: filter → prompt → workflow → ComfyUI → local images.

    Raises ``RuntimeError`` for user-visible failures.
    """
    # 1. Safety + prompt conversion
    spec = build_prompt_spec(user_text)
    if spec.blocked:
        raise RuntimeError(spec.block_reason or "此请求被安全过滤拦截。")

    # 2. Load workflow
    wf_path = config.comfyui_workflow_api_path
    if not wf_path:
        raise RuntimeError(
            "未配置图片生成工作流路径。请在 .env 中设置 COMFYUI_WORKFLOW_API_PATH。"
        )
    workflow = load_workflow(wf_path)

    # 3. Patch
    workflow = patch_workflow(workflow, spec, config)

    # 4. Generate
    client = ComfyUIClient(
        config.comfyui_base_url,
        config.comfyui_timeout_seconds,
        config.comfyui_client_id,
    )
    return client.generate(workflow, _resolve_output_dir())


def try_generate_image(user_text: str) -> tuple[list[GeneratedImage] | None, str]:
    """Thread-safe wrapper with single-task lock.

    Returns ``(images, error_message)`` — exactly one will be non-empty.
    """
    if not config.image_enable:
        return None, (
            "图片生成功能未启用。"
            "请在 .env 中设置 IMAGE_ENABLE=true，并确认 ComfyUI 正在运行。"
        )

    if config.image_single_task_lock:
        acquired = IMAGE_GENERATION_LOCK.acquire(blocking=False)
        if not acquired:
            return None, "现在已经有图片任务在运行，请等当前任务结束后再试。"
    else:
        acquired = False

    try:
        images = generate_image_from_text(user_text)
        return images, ""
    except RuntimeError as exc:
        return None, f"图片生成失败：{exc}"
    except Exception:
        logger.exception("Unexpected image generation error")
        return None, "图片生成失败：内部错误，请稍后再试。"
    finally:
        if acquired:
            IMAGE_GENERATION_LOCK.release()
