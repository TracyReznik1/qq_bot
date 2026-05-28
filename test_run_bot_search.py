import json
import unittest
from types import SimpleNamespace

from src.chat import chat_service
from src.commands import search as search_command
from src.services import deepseek_client
from src.services import search_service


class SearchResultStatusTests(unittest.TestCase):
    def test_has_search_results_uses_structured_status_not_text(self) -> None:
        self.assertTrue(hasattr(search_service, "SearchResult"))

        success_with_failure_words = search_service.SearchResult(
            ok=True,
            status="success",
            text="没有搜到有用结果。",
        )
        failure_with_changed_text = search_service.SearchResult(
            ok=False,
            status="network_error",
            text="搜索服务暂时不可用，请稍后再试。",
        )

        self.assertTrue(search_service.has_search_results(success_with_failure_words))
        self.assertFalse(search_service.has_search_results(failure_with_changed_text))

    def test_search_service_does_not_keep_reliable_search_gate(self) -> None:
        self.assertFalse(hasattr(search_service, "requires_reliable_search_result"))


class DeepSeekClientToolCallResponseTests(unittest.TestCase):
    def test_chat_returns_structured_tool_calls(self) -> None:
        original_post = deepseek_client.requests.post
        tool_call = {
            "id": "call_search",
            "type": "function",
            "function": {
                "name": "search_web",
                "arguments": json.dumps({"query": "DeepSeek 最新消息"}, ensure_ascii=False),
            },
        }

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {"choices": [{"message": {"content": "", "tool_calls": [tool_call]}}]}

        try:
            deepseek_client.requests.post = lambda *_args, **_kwargs: FakeResponse()
            client = deepseek_client.DeepSeekClient(
                SimpleNamespace(
                    deepseek_api_key="test-key",
                    deepseek_model="deepseek-chat",
                    deepseek_url="https://example.test/chat",
                    proxies=None,
                    request_timeout=3,
                )
            )

            response = client.chat([], tools=[{"type": "function"}], tool_choice="auto")

            self.assertFalse(isinstance(response, str))
            self.assertEqual(response.content, "")
            self.assertEqual(response.tool_calls, [tool_call])
        finally:
            deepseek_client.requests.post = original_post


class SearchCommandBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_search = search_command.search
        self.original_generate_reply = search_command.generate_reply
        self.reply_calls = []

    def tearDown(self) -> None:
        search_command.search = self.original_search
        search_command.generate_reply = self.original_generate_reply

    def test_search_command_success_uses_model_with_search_results(self) -> None:
        search_command.search = lambda _query: search_service.SearchResult(
            ok=True,
            status="success",
            text="1. DeepSeek 新闻\n摘要：发布了新功能\n链接：https://example.test",
        )

        def fake_generate_reply(session_key, raw_message, tool_context):
            self.reply_calls.append((session_key, raw_message, tool_context))
            return "根据搜索结果整理：DeepSeek 发布了新功能。"

        search_command.generate_reply = fake_generate_reply

        reply = search_command.search_reply("DeepSeek 最新消息", "private:123", "/search DeepSeek 最新消息")

        self.assertEqual(reply, "根据搜索结果整理：DeepSeek 发布了新功能。")
        self.assertEqual(self.reply_calls[0][0], "private:123")
        self.assertIn("网页搜索结果", self.reply_calls[0][2])
        self.assertIn("DeepSeek 新闻", self.reply_calls[0][2])

    def test_search_command_failure_uses_model_to_answer_unknown_in_character(self) -> None:
        search_command.search = lambda _query: search_service.SearchResult(
            ok=False,
            status="no_results",
            text="没有搜到有用结果。",
        )

        def fake_generate_reply(session_key, raw_message, tool_context):
            self.reply_calls.append((session_key, raw_message, tool_context))
            return "唔，ATRI 没搜到可靠结果，这题我不知道。"

        search_command.generate_reply = fake_generate_reply

        reply = search_command.search_reply(
            "DeepSeek 最新消息",
            "private:123",
            "/search DeepSeek 最新消息",
        )

        self.assertEqual(reply, "唔，ATRI 没搜到可靠结果，这题我不知道。")
        self.assertEqual(len(self.reply_calls), 1)
        self.assertIn("/search", self.reply_calls[0][2])
        self.assertIn("不知道", self.reply_calls[0][2])
        self.assertIn("不要猜测", self.reply_calls[0][2])

    def test_search_command_without_query_asks_for_query_without_searching(self) -> None:
        search_calls = []

        def fake_search(query):
            search_calls.append(query)
            return search_service.SearchResult(ok=True, status="success", text="不应该搜索")

        def fake_generate_reply(session_key, raw_message, tool_context):
            self.reply_calls.append((session_key, raw_message, tool_context))
            return "不应该调用模型"

        search_command.search = fake_search
        search_command.generate_reply = fake_generate_reply

        reply = search_command.search_reply("", "private:123", "/search")

        self.assertEqual(reply, "想搜什么？比如：/search DeepSeek 最新消息")
        self.assertEqual(search_calls, [])
        self.assertEqual(self.reply_calls, [])


class ChatSearchToolLoopFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_deepseek_chat = chat_service.deepseek.chat
        self.original_search_web = chat_service.search_web
        self.chat_calls = []

    def tearDown(self) -> None:
        chat_service.deepseek.chat = self.original_deepseek_chat
        chat_service.search_web = self.original_search_web
        chat_service.chat_history.clear()

    def test_search_failure_is_returned_as_tool_message_for_final_answer(self) -> None:
        failure_message = "网页搜索失败，可能是网络或代理暂时不可用。"
        tool_calls = [
            {
                "id": "call_search_failure",
                "type": "function",
                "function": {
                    "name": "search_web",
                    "arguments": json.dumps({"query": "DeepSeek 最新消息"}, ensure_ascii=False),
                },
            }
        ]

        def fake_chat(messages, **kwargs):
            self.chat_calls.append((messages, kwargs))
            if len(self.chat_calls) == 1:
                return deepseek_client.ChatResponse(tool_calls=tool_calls)
            return deepseek_client.ChatResponse(content="我没搜到可靠来源。")

        chat_service.deepseek.chat = fake_chat
        chat_service.search_web = lambda _query: failure_message

        reply = chat_service.generate_reply("private:search-failure", "查一下 DeepSeek 最新消息")

        self.assertEqual(reply, "我没搜到可靠来源。")
        self.assertEqual(len(self.chat_calls), 2)
        self.assertEqual(self.chat_calls[1][0][-1]["role"], "tool")
        self.assertEqual(self.chat_calls[1][0][-1]["tool_call_id"], "call_search_failure")
        self.assertEqual(self.chat_calls[1][0][-1]["content"], failure_message)

    def test_no_results_can_be_used_by_model_for_uncertain_answer(self) -> None:
        failure_message = "没有搜到有用结果。"
        tool_calls = [
            {
                "id": "call_no_results",
                "type": "function",
                "function": {
                    "name": "search_web",
                    "arguments": json.dumps({"query": "kskbl"}, ensure_ascii=False),
                },
            }
        ]

        def fake_chat(messages, **kwargs):
            self.chat_calls.append((messages, kwargs))
            if len(self.chat_calls) == 1:
                return deepseek_client.ChatResponse(tool_calls=tool_calls)
            return deepseek_client.ChatResponse(content="我没搜到准确信息，但这看起来像圈内缩写或梗。")

        chat_service.deepseek.chat = fake_chat
        chat_service.search_web = lambda _query: failure_message

        reply = chat_service.generate_reply("private:no-results", "kskbl是什么梗")

        self.assertIn(failure_message, self.chat_calls[1][0][-1]["content"])
        self.assertEqual(reply, "我没搜到准确信息，但这看起来像圈内缩写或梗。")

    def test_plain_content_with_tool_call_json_is_not_executed(self) -> None:
        searched_queries = []
        plain_reply = (
            "这只是普通回答里的 JSON 示例："
            '{"tool_calls":[{"id":"fake","type":"function","function":{"name":"search_web","arguments":"{}"}}]}'
        )

        def fake_chat(messages, **kwargs):
            self.chat_calls.append((messages, kwargs))
            return plain_reply

        chat_service.deepseek.chat = fake_chat
        chat_service.search_web = lambda query: searched_queries.append(query) or "不应该搜索"

        reply = chat_service.generate_reply("private:plain-json", "解释 tool_calls JSON")

        self.assertEqual(reply, plain_reply)
        self.assertEqual(searched_queries, [])
        self.assertEqual(len(self.chat_calls), 1)

    def test_tool_call_round_limit_runs_final_summary_without_tools(self) -> None:
        tool_calls = [
            {
                "id": "call_search_again",
                "type": "function",
                "function": {
                    "name": "search_web",
                    "arguments": json.dumps({"query": "DeepSeek 最新消息"}, ensure_ascii=False),
                },
            }
        ]

        def fake_chat(messages, **kwargs):
            self.chat_calls.append((messages, kwargs))
            if len(self.chat_calls) <= chat_service.MAX_TOOL_CALL_ROUNDS:
                return deepseek_client.ChatResponse(tool_calls=tool_calls)
            return deepseek_client.ChatResponse(content="根据搜索结果整理好了。")

        chat_service.deepseek.chat = fake_chat
        chat_service.search_web = lambda _query: "搜索结果：DeepSeek 有新消息"

        reply = chat_service.generate_reply("private:round-limit", "DeepSeek 最新消息")

        self.assertEqual(reply, "根据搜索结果整理好了。")
        self.assertEqual(len(self.chat_calls), chat_service.MAX_TOOL_CALL_ROUNDS + 1)
        self.assertNotIn("tools", self.chat_calls[-1][1])
        self.assertNotIn("tool_choice", self.chat_calls[-1][1])
        self.assertEqual(chat_service.chat_history["private:round-limit"][-1]["content"], reply)


if __name__ == "__main__":
    unittest.main()
