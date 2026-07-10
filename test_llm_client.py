"""Unit tests for LLM fallback chain (mock-based, no real API calls)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services.llm_client import (
    FallbackLLMClient,
    _MODEL_CAPABILITIES,
    _build_chain,
    _is_retryable_error,
    _model_supports_tools,
    get_llm_client,
)
from src.services.llm_types import ChatResponse, LLMModelSpec


class FallbackModelCapabilityTests(unittest.TestCase):
    def test_gemma_defaults_to_no_tools(self) -> None:
        self.assertFalse(_model_supports_tools("gemini", "gemma-4-26b-a4b-it"))

    def test_gemini_flash_lite_supports_tools(self) -> None:
        self.assertTrue(
            _model_supports_tools("gemini", "gemini-3.1-flash-lite")
        )

    def test_deepseek_supports_tools(self) -> None:
        self.assertTrue(_model_supports_tools("deepseek", "deepseek-v4-flash"))
        self.assertTrue(_model_supports_tools("deepseek", "deepseek-v4-pro"))


class RetryableErrorTests(unittest.TestCase):
    def test_connection_error_is_retryable(self) -> None:
        import requests
        self.assertTrue(_is_retryable_error(requests.ConnectionError()))

    def test_timeout_is_retryable(self) -> None:
        import requests
        self.assertTrue(_is_retryable_error(requests.Timeout()))

    def test_http_429_is_retryable(self) -> None:
        import requests
        response = SimpleNamespace(status_code=429)
        exc = requests.HTTPError(response=response)
        self.assertTrue(_is_retryable_error(exc))

    def test_http_500_is_retryable(self) -> None:
        import requests
        response = SimpleNamespace(status_code=500)
        exc = requests.HTTPError(response=response)
        self.assertTrue(_is_retryable_error(exc))

    def test_http_503_is_retryable(self) -> None:
        import requests
        response = SimpleNamespace(status_code=503)
        exc = requests.HTTPError(response=response)
        self.assertTrue(_is_retryable_error(exc))

    def test_http_404_is_not_retryable(self) -> None:
        import requests
        response = SimpleNamespace(status_code=404)
        exc = requests.HTTPError(response=response)
        self.assertFalse(_is_retryable_error(exc))

    def test_value_error_is_not_retryable(self) -> None:
        self.assertFalse(_is_retryable_error(ValueError("not an HTTP error")))


class FallbackChainSkipNoToolsTests(unittest.TestCase):
    def test_skips_gemma_when_tools_provided(self) -> None:
        """Gemma should be skipped when tools are passed."""
        chain = [
            LLMModelSpec("gemini", "gemini-3.1-flash-lite", supports_tools=True),
            LLMModelSpec("gemini", "gemma-4-26b-a4b-it", supports_tools=False),
            LLMModelSpec("deepseek", "deepseek-v4-flash", supports_tools=True),
        ]

        class CountingClient:
            call_count = 0

            def chat(self, messages, **kwargs):
                CountingClient.call_count += 1
                model = kwargs.get("model", "")
                if model == "gemini-3.1-flash-lite":
                    raise RuntimeError(
                        "Gemini API key is missing. Set GEMINI_API_KEY in .env."
                    )
                return ChatResponse(content=f"Reply from {model}")

        client = FallbackLLMClient(chain)
        # Override internal client factory
        client._get_client = lambda spec: CountingClient()

        result = client.chat(
            [{"role": "user", "content": "hello"}],
            tools=[{"type": "function"}],
        )

        # Gemini flash should fail (no key), Gemma should be skipped,
        # DeepSeek should succeed.
        self.assertIn("deepseek-v4-flash", result.content)
        # Gemma should not have been called
        self.assertNotIn("gemma", result.content)


class FallbackChainFullFailureTests(unittest.TestCase):
    def test_all_models_exhausted_raises_unified_error(self) -> None:
        chain = [
            LLMModelSpec("gemini", "gemini-3.1-flash-lite", supports_tools=True),
        ]

        class AlwaysFailingClient:
            def chat(self, messages, **kwargs):
                raise RuntimeError("no key")

        client = FallbackLLMClient(chain)
        client._get_client = lambda spec: AlwaysFailingClient()

        with self.assertRaises(RuntimeError) as ctx:
            client.chat([{"role": "user", "content": "test"}])
        self.assertIn("模型暂时不可用", str(ctx.exception))


class FallbackChainSuccessTests(unittest.TestCase):
    def test_first_model_succeeds(self) -> None:
        chain = [
            LLMModelSpec("gemini", "gemini-3.1-flash-lite", supports_tools=True),
            LLMModelSpec("deepseek", "deepseek-v4-flash", supports_tools=True),
        ]

        class SuccessClient:
            def chat(self, messages, **kwargs):
                return ChatResponse(content="Hello from Gemini")

        client = FallbackLLMClient(chain)
        client._get_client = lambda spec: SuccessClient()

        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "Hello from Gemini")
        self.assertEqual(result.tool_calls, [])

    def test_fallback_to_second_when_first_fails(self) -> None:
        import requests

        chain = [
            LLMModelSpec("gemini", "gemini-3.1-flash-lite", supports_tools=True),
            LLMModelSpec("deepseek", "deepseek-v4-flash", supports_tools=True),
        ]

        class GeminiFailsDeepSeekWorksClient:
            def chat(self, messages, **kwargs):
                model = kwargs.get("model", "")
                if "gemini" in model:
                    response = SimpleNamespace(status_code=500)
                    raise requests.HTTPError(response=response)
                return ChatResponse(content="Hello from DeepSeek")

        client = FallbackLLMClient(chain)
        client._get_client = lambda spec: GeminiFailsDeepSeekWorksClient()

        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "Hello from DeepSeek")


class FallbackChainEmptyContentTests(unittest.TestCase):
    def test_empty_content_and_no_tools_triggers_fallback(self) -> None:
        chain = [
            LLMModelSpec("gemini", "gemini-3.1-flash-lite", supports_tools=True),
            LLMModelSpec("deepseek", "deepseek-v4-flash", supports_tools=True),
        ]

        call_count = [0]

        class EmptyThenWorksClient:
            def chat(self, messages, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return ChatResponse(content="", tool_calls=[])
                return ChatResponse(content="Recovered by fallback")

        client = FallbackLLMClient(chain)
        client._get_client = lambda spec: EmptyThenWorksClient()

        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "Recovered by fallback")
        self.assertEqual(call_count[0], 2)


class ChainBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        # Backup
        import src.config
        self._original_config = src.config.config

    def tearDown(self) -> None:
        import src.config
        src.config.config = self._original_config
        import src.services.llm_client as lc
        lc._llm_client = None

    def _make_fake_config(self, **overrides):
        defaults = {
            "gemini_api_key": "",
            "gemini_model": "gemini-3.1-flash-lite",
            "gemini_url": "https://example.test/gemini",
            "deepseek_api_key": "",
            "deepseek_model": "deepseek-v4-flash",
            "deepseek_url": "https://example.test/deepseek",
            "llm_primary_provider": "gemini",
            "llm_primary_model": "",
            "llm_fallback_1_provider": "gemini",
            "llm_fallback_1_model": "gemma-4-26b-a4b-it",
            "llm_fallback_2_provider": "deepseek",
            "llm_fallback_2_model": "deepseek-v4-flash",
            "llm_fallback_3_provider": "deepseek",
            "llm_fallback_3_model": "deepseek-v4-pro",
            "proxies": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_default_chain_has_4_models(self) -> None:
        cfg = self._make_fake_config()
        chain = _build_chain(cfg)
        self.assertEqual(len(chain), 4)
        self.assertEqual(chain[0].provider, "gemini")
        self.assertEqual(chain[0].model, "gemini-3.1-flash-lite")
        self.assertFalse(chain[1].supports_tools)  # Gemma

    def test_deepseek_only_chain(self) -> None:
        cfg = self._make_fake_config(
            llm_primary_provider="deepseek",
            llm_primary_model="deepseek-v4-flash",
            llm_fallback_1_provider="deepseek",
            llm_fallback_1_model="deepseek-v4-pro",
            llm_fallback_2_provider="",
            llm_fallback_3_provider="",
        )
        chain = _build_chain(cfg)
        self.assertEqual(len(chain), 2)
        self.assertTrue(all(spec.provider == "deepseek" for spec in chain))

    def test_empty_fallback_slots_excluded(self) -> None:
        cfg = self._make_fake_config(
            llm_fallback_1_provider="",
            llm_fallback_2_provider="",
            llm_fallback_3_provider="",
        )
        chain = _build_chain(cfg)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].model, "gemini-3.1-flash-lite")

    def test_primary_model_uses_provider_default_when_empty(self) -> None:
        cfg = self._make_fake_config(
            llm_primary_provider="deepseek",
            llm_primary_model="",
            deepseek_model="deepseek-v4-pro",
            llm_fallback_1_provider="",
            llm_fallback_2_provider="",
            llm_fallback_3_provider="",
        )
        chain = _build_chain(cfg)
        self.assertEqual(chain[0].provider, "deepseek")
        self.assertEqual(chain[0].model, "deepseek-v4-pro")


class GetLLMClientSingletonTests(unittest.TestCase):
    def tearDown(self) -> None:
        import src.services.llm_client as lc
        lc._llm_client = None

    def test_returns_same_instance(self) -> None:
        c1 = get_llm_client()
        c2 = get_llm_client()
        self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()
