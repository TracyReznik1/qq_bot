# Search Refactoring Task Tracker

| Task ID | Task Description | Status | Evidence |
|---|---|:---:|---|
| config-llm-router | 扩展配置与 LLM 客户端支持 SearchRouter（`src/config.py`、`src/services/llm_client.py`、`src/util.py`、`.env.example`） | COMPLETED | `python -B -m unittest tests.test_llm_tool_affinity tests.test_llm_image_fallback` (8 passed), `get_router_llm_client()` instantiates properly |
| search-core-router | 移植检索收益路由器与管线短路优化（`src/search/simple/models.py`、`router.py`、`pipeline.py`、`__init__.py`） | COMPLETED | `python -B -m unittest tests.test_simple_search_router tests.test_simple_search_pipeline -v` (13 passed) |
| chat-service-integrate | 融合聊天服务智能路由裁决与错误隔离，严格保留现有 B 站视频直读（`src/chat/chat_service.py`、`src/main.py`） | COMPLETED | `python -B -m unittest tests.test_simple_search_chat_flow tests.test_main_image_flow -v` (36 passed) |
| tests-regression | 移植路由测试并更新单测，执行全量回归验证（550+ tests） | COMPLETED | `python -B -m unittest discover -s tests -t . -v` (560 passed in 15.636s), `git diff --check` clean |
