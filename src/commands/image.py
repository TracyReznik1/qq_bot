"""``/image`` command — ComfyUI / Anima local image generation.

Requires ``IMAGE_ENABLE=true`` in ``.env`` and a running ComfyUI Desktop.
"""

from pathlib import Path

from src.config import config
from src.services.image_generation_service import try_generate_image
from src.services.onebot_client import build_cq_image_file


def image_reply(query: str, context) -> str:
    """Return a plain-text reply for the /image command.

    The caller (``src/commands/__init__.py``) wraps the result in
    ``CommandResult`` via ``_text_result()``.
    """
    user_text = query.strip()

    # 1. Not enabled
    if not config.image_enable:
        return (
            "图片生成功能未启用。"
            "请在 .env 中设置 IMAGE_ENABLE=true，并确认 ComfyUI 正在运行。"
        )

    # 2. Empty input
    if not user_text:
        return (
            "用法：/image 你想画的内容\n"
            "例如：/image 夏目安安头像，蓝色雨夜氛围，温柔看向镜头"
        )

    # 3. Admin-only check
    if config.image_admin_only and str(context.uid) not in config.admin_qq_ids:
        return "图片生成功能目前仅管理员可用。"

    # 4. Validate workflow path
    wf = config.comfyui_workflow_api_path
    if not wf or not Path(wf).exists():
        return (
            "图片生成工作流未配置或文件不存在。"
            "请在 .env 中设置正确的 COMFYUI_WORKFLOW_API_PATH。"
        )

    images, error = try_generate_image(user_text)
    if error:
        return error

    if images:
        lines = ["收到，生成完成。"]
        for img in images:
            safe_path = str(Path(img.path).resolve())
            lines.append(build_cq_image_file(safe_path))
        return "\n".join(lines)

    return "图片生成完成但未获取到输出文件。"
