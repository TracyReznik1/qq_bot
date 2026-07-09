from src.chat.chat_service import generate_reply
from src.services.search_service import has_search_results, search
from src.services.search_service import normalize_search_query
from src.services.url_fetch_service import extract_first_url, fetch_url
from src.services.video_service import has_video_url, understand_video


def search_reply(query: str, session_key: str, raw_message: str) -> str:
    query = normalize_search_query(query)
    if not query:
        return "想搜什么？比如：/search DeepSeek 最新消息"

    if has_video_url(query):
        video_result = understand_video(query)
        if video_result.ok:
            tool_context = (
                "这是 /search 命令收到视频链接后的直读结果。请按 ATRI 的角色设定回答用户："
                "基于标题、简介、字幕或页面文字总结重点；不要声称已经看过完整画面或听过完整音频。"
                "如果字幕或页面文字不足，要明确说明不确定。\n"
                f"视频理解结果：\n{video_result.text}"
            )
        else:
            tool_context = (
                "这是 /search 命令收到视频链接后的读取失败结果。请按 ATRI 的角色设定回答用户："
                "说明当前无法可靠理解这个视频，不要猜测视频内容。\n"
                f"视频理解结果：\n{video_result.text}"
            )
        return generate_reply(session_key, raw_message, tool_context)

    if extract_first_url(query):
        fetch_result = fetch_url(query)
        if fetch_result.ok:
            tool_context = (
                "这是 /search 命令收到 URL 后的直读结果。请按 ATRI 的角色设定回答用户："
                "结合网页标题和正文摘录总结重点；如果摘录不足以支撑结论，要明确说明不确定。\n"
                f"URL 直读结果：\n{fetch_result.text}"
            )
        else:
            tool_context = (
                "这是 /search 命令收到 URL 后的读取失败结果。请按 ATRI 的角色设定回答用户："
                "说明网页没有读到可靠内容，所以无法确认；不要猜测，不要编造页面内容。\n"
                f"URL 直读结果：\n{fetch_result.text}"
            )
        return generate_reply(session_key, raw_message, tool_context)

    search_result = search(query)
    if not has_search_results(search_result):
        tool_context = (
            "这是 /search 命令的搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到可靠结果，所以不知道或无法确认；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{search_result.text}"
        )
    else:
        tool_context = f"网页搜索结果：\n{search_result.text}"

    return generate_reply(session_key, raw_message, tool_context)
