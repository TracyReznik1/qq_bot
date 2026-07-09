from src.chat.chat_service import generate_reply
from src.services.url_fetch_service import extract_first_url, fetch_url


def url_reply(query: str, session_key: str, raw_message: str) -> str:
    if not extract_first_url(query):
        return "想读哪个网页？比如：/url https://example.com"

    fetch_result = fetch_url(query)
    if fetch_result.ok:
        tool_context = (
            "这是 /url 命令的 URL 直读结果。请按 ATRI 的角色设定回答用户："
            "结合网页标题和正文摘录总结重点；如果摘录不足以支撑结论，要明确说明不确定。\n"
            f"URL 直读结果：\n{fetch_result.text}"
        )
    else:
        tool_context = (
            "这是 /url 命令的 URL 读取失败结果。请按 ATRI 的角色设定回答用户："
            "说明网页没有读到可靠内容，所以无法确认；不要猜测，不要编造页面内容。\n"
            f"URL 直读结果：\n{fetch_result.text}"
        )

    return generate_reply(session_key, raw_message, tool_context)
