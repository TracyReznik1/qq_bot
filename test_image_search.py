"""Unit tests for /pic command and image_search_service.

All external calls (Tavily, HTTP downloads, OneBot) are mocked.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.config as config_module
from src.commands import pic as pic_mod
from src.services import image_search_service as iss_mod


class _ConfigSwapBase(unittest.TestCase):
    """Base class that swaps config for tests, restoring on tearDown."""

    def setUp(self):
        self._old_config = config_module.config

    def tearDown(self):
        config_module.config = self._old_config
        # Restore module-level references
        pic_mod.config = self._old_config
        iss_mod.config = self._old_config

    def _set(self, **overrides):
        new_dict = {}
        for fn in self._old_config.__dataclass_fields__:
            new_dict[fn] = getattr(self._old_config, fn)
        new_dict.update(overrides)
        fake = SimpleNamespace(**new_dict)
        # Config.proxies is a @property, not a dataclass field — add it manually
        proxy_url = new_dict.get("proxy_url", "")
        fake.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        config_module.config = fake
        pic_mod.config = fake
        iss_mod.config = fake
        return fake


class PicCommandDisabledTests(_ConfigSwapBase):
    """Tests for /pic when IMAGE_SEARCH_ENABLE=false."""

    def test_pic_disabled_returns_hint(self):
        self._set(image_search_enable=False)
        ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫")
        result = pic_mod.pic_reply("猫", ctx)
        self.assertIn("未启用", result)

    def test_pic_empty_query_returns_usage(self):
        self._set(image_search_enable=True)
        ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic")
        result = pic_mod.pic_reply("", ctx)
        self.assertIn("用法", result)


class PicCommandParsingTests(_ConfigSwapBase):
    """Tests for /pic keyword and count parsing."""

    def test_default_limit_is_one(self):
        self._set(image_search_enable=True)
        with patch.object(pic_mod, "search_and_download_images", return_value=[]) as mock_search:
            ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫")
            pic_mod.pic_reply("猫", ctx)
        mock_search.assert_called_once_with("猫", limit=1)

    def test_trailing_number_sets_limit(self):
        self._set(image_search_enable=True)
        with patch.object(pic_mod, "search_and_download_images", return_value=[]) as mock_search:
            ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫 3")
            pic_mod.pic_reply("猫 3", ctx)
        mock_search.assert_called_once_with("猫", limit=3)

    def test_limit_capped_at_send_max(self):
        self._set(image_search_enable=True, image_search_send_max=2)
        with patch.object(pic_mod, "search_and_download_images", return_value=[]) as mock_search:
            ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫 5")
            pic_mod.pic_reply("猫 5", ctx)
        mock_search.assert_called_once_with("猫", limit=2)

    def test_send_max_never_exceeds_three(self):
        self._set(image_search_enable=True, image_search_send_max=10)
        with patch.object(pic_mod, "search_and_download_images", return_value=[]) as mock_search:
            ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫 10")
            pic_mod.pic_reply("猫 10", ctx)
        # limit should be capped at 3 even if send_max is 10
        mock_search.assert_called_once_with("猫", limit=3)


class PicCommandResultTests(_ConfigSwapBase):
    """Tests for /pic response formatting."""

    def test_no_results_returns_friendly_message(self):
        self._set(image_search_enable=True)
        with patch.object(pic_mod, "search_and_download_images", return_value=[]):
            ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic xyz")
            result = pic_mod.pic_reply("xyz", ctx)
        self.assertIn("没有找到", result)

    def test_success_includes_cq_image(self):
        self._set(image_search_enable=True)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0")
            tmp_path = f.name
        try:
            mock_result = iss_mod.ImageSearchResult(
                local_path=tmp_path,
                image_url="https://example.com/cat.jpg",
                source_url="https://example.com/gallery",
                title="Cat Photo",
                provider="tavily",
            )
            with patch.object(pic_mod, "search_and_download_images", return_value=[mock_result]):
                ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic 猫")
                result = pic_mod.pic_reply("猫", ctx)
            self.assertIn("[CQ:image,file=", result)
            self.assertIn("Cat Photo", result)
            self.assertIn("来源: https://example.com/gallery", result)
        finally:
            os.unlink(tmp_path)


class ImageSearchServiceTests(_ConfigSwapBase):
    """Tests for image_search_service download and validation."""

    def test_download_rejects_non_image_content_type(self):
        self._set()
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_resp.raise_for_status = MagicMock()
            with patch.object(iss_mod, "try_proxied_get", return_value=mock_resp):
                result = iss_mod._download_image("https://example.com/page.html", Path(tmpdir))
            self.assertIsNone(result)

    def test_download_accepts_jpeg_content_type(self):
        self._set()
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Type": "image/jpeg"}
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content = MagicMock(return_value=[b"\xff\xd8\xff\xe0" * 100])
            with patch.object(iss_mod, "try_proxied_get", return_value=mock_resp):
                result = iss_mod._download_image("https://example.com/cat.jpg", Path(tmpdir))
            self.assertIsNotNone(result)
            self.assertTrue(result.exists())
            self.assertTrue(result.name.endswith(".jpg"))

    def test_download_rejects_oversized_image(self):
        self._set(image_search_max_download_mb=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Type": "image/png"}
            mock_resp.raise_for_status = MagicMock()
            chunk_size = 600 * 1024
            mock_resp.iter_content = MagicMock(return_value=[
                b"\x00" * chunk_size,
                b"\x00" * chunk_size,
            ])
            with patch.object(iss_mod, "try_proxied_get", return_value=mock_resp):
                result = iss_mod._download_image("https://example.com/big.png", Path(tmpdir))
            self.assertIsNone(result)

    def test_cache_dir_is_under_atri_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "image_search_cache")
            self._set(image_search_cache_dir=cache_path)
            result = iss_mod._cache_dir()
            self.assertTrue(str(result).endswith("image_search_cache"))
            self.assertTrue(result.exists())


class PicCommandRoutingTests(unittest.TestCase):
    """/pic routes correctly through the command system."""

    def test_pic_is_registered_command(self):
        from src.commands import COMMANDS
        self.assertIn("pic", COMMANDS)
        self.assertIn("p", COMMANDS)

    def test_pic_routes_to_command_not_chat(self):
        from src.router import route_message
        route = route_message("/pic 猫")
        self.assertEqual(route.command, "pic")
        self.assertEqual(route.query, "猫")


class OrdinaryChatBoundaryTests(unittest.TestCase):
    """Image search tools must not be exposed in ordinary chat."""

    def test_chat_tools_do_not_include_image_search(self):
        """Verify that search_and_download_images and pic_reply
        are not exposed as tools in ordinary chat."""
        from src.chat import chat_service
        source = Path(chat_service.__file__).read_text(encoding="utf-8")
        self.assertNotIn("image_search", source)
        self.assertNotIn("pic_reply", source)
        self.assertNotIn("search_and_download_images", source)


class TavilyImageSearchTests(_ConfigSwapBase):
    """Tests for the Tavily image search integration."""

    def test_tavily_unavailable_returns_empty(self):
        self._set(tavily_api_key="")
        with patch.object(iss_mod, "TavilyClient", None):
            results = iss_mod._tavily_image_search("cat", 5)
        self.assertEqual(results, [])

    def test_tavily_image_results_are_extracted(self):
        self._set()
        mock_client_instance = MagicMock()
        mock_client_instance.search.return_value = {
            "images": [
                "https://example.com/cat1.jpg",
                "https://example.com/cat2.png",
            ],
            "results": [],
        }
        mock_tavily_cls = MagicMock(return_value=mock_client_instance)
        with patch.object(iss_mod, "TavilyClient", mock_tavily_cls):
            results = iss_mod._tavily_image_search("cat", 5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].image_url, "https://example.com/cat1.jpg")

    def test_search_and_download_skips_failed_downloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._set(image_search_cache_dir=tmpdir, image_search_enable=True)
            candidates = [
                iss_mod._RawImageHit(image_url="https://fail.com/a.jpg"),
                iss_mod._RawImageHit(image_url="https://fail.com/b.jpg"),
            ]
            with patch.object(iss_mod, "_tavily_image_search", return_value=candidates), \
                 patch.object(iss_mod, "_download_image", return_value=None):
                results = iss_mod.search_and_download_images("test", limit=2)
            self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
