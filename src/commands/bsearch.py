from src.chat import chat_service
from src.services import bilibili_search


def bsearch_reply(query: str, session_key: str, raw_message: str) -> str:
    query = query.strip()
    if not query:
        return "想搜哪个B站用户？比如：/bsearch 大东彦"

    result = bilibili_search.search_bilibili_users(query)
    if result.ok:
        tool_context = f"B站用户搜索结果：\n{result.text}"
    else:
        tool_context = (
            "这是 /bsearch 命令的 B站用户搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到匹配的 B站用户；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{result.text}"
        )
    return chat_service.generate_reply(session_key, raw_message, tool_context)
