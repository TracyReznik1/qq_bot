from src.chat import chat_service
from src.services import bilibili_search


def buser_reply(query: str, session_key: str, raw_message: str) -> str:
    query = query.strip()
    if not query:
        return "想搜哪个B站用户？比如：/buser 大东彦"

    result = bilibili_search.search_bilibili_users(query)
    if result.ok:
        tool_context = f"B站用户搜索结果：\n{result.text}"
    else:
        tool_context = (
            "这是 /buser 命令的 B站用户搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到匹配的 B站用户；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{result.text}"
        )
    return chat_service.generate_reply(session_key, raw_message, tool_context)


def bfuser_reply(query: str, session_key: str, raw_message: str) -> str:
    query = query.strip()
    if not query:
        return "想筛词搜哪个B站用户？比如：/bfuser 大东彦是谁"

    result = bilibili_search.search_filtered_bilibili_users(query)
    if result.ok:
        tool_context = f"B站用户搜索结果：\n{result.text}"
    else:
        tool_context = (
            "这是 /bfuser 命令的 B站用户筛词搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到匹配的 B站用户；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{result.text}"
        )
    return chat_service.generate_reply(session_key, raw_message, tool_context)


bsearch_reply = buser_reply
bfsearch_reply = bfuser_reply


def bvideo_reply(query: str, session_key: str, raw_message: str) -> str:
    query = query.strip()
    if not query:
        return "想搜哪个B站视频？比如：/bvideo 无畏契约 教学"

    result = bilibili_search.search_bilibili_videos(query)
    if result.ok:
        return result.text
    else:
        tool_context = (
            "这是 /bvideo 命令的 B站视频搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到匹配的 B站视频；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{result.text}"
        )
    return chat_service.generate_reply(session_key, raw_message, tool_context)


def bfvideo_reply(query: str, session_key: str, raw_message: str) -> str:
    query = query.strip()
    if not query:
        return "想筛词搜哪个B站视频？比如：/bfvideo 搜索视频 comfyvibe 这个视频"

    result = bilibili_search.search_filtered_bilibili_videos(query)
    if result.ok:
        return result.text
    else:
        tool_context = (
            "这是 /bfvideo 命令的 B站视频筛词搜索失败结果。请按 ATRI 的角色设定回答用户："
            "说明没有搜到匹配的 B站视频；不要猜测，不要编造成确定事实。\n"
            f"搜索状态：\n{result.text}"
        )
    return chat_service.generate_reply(session_key, raw_message, tool_context)
