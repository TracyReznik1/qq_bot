from src.chat.chat_service import generate_reply
from src.services.video_service import has_video_url, understand_video


def video_reply(query: str, session_key: str, raw_message: str) -> str:
    if not has_video_url(query):
        return "想让我看哪个视频？比如：/video https://www.bilibili.com/video/BV..."

    result = understand_video(query)
    if result.ok:
        tool_context = (
            "这是 /video 命令的视频理解结果。请按 ATRI 的角色设定回答用户："
            "基于标题、简介、字幕或页面文字总结重点；不要声称已经看过完整画面或听过完整音频。"
            "如果字幕或页面文字不足，要明确说明不确定。\n"
            f"视频理解结果：\n{result.text}"
        )
    else:
        tool_context = (
            "这是 /video 命令的视频理解失败结果。请按 ATRI 的角色设定回答用户："
            "说明当前只能读取支持平台的页面信息或字幕，不能猜测视频内容。\n"
            f"视频理解结果：\n{result.text}"
        )
    return generate_reply(session_key, raw_message, tool_context)
