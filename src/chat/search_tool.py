from src.services.search_service import web_search


def search_web(query: str) -> str:
    return web_search(query)
