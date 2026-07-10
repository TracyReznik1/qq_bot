"""Unit tests for OneBot image send with base64 fallback.

All OneBot HTTP calls are mocked — no real network.
"""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.config as config_module
from src.services.onebot_client import (
    OneBotClient,
    build_cq_image_file,
    build_cq_image_base64,
)


def _fake_config(**overrides):
    """Build a SimpleNamespace that quacks like Config."""
    defaults = {
        "onebot_url": "http://127.0.0.1:3000",
        "onebot_access_token": "",
        "request_timeout": 18,
        "image_send_base64_fallback": True,
        "image_send_base64_max_mb": 8,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _small_jpeg(path: Path) -> None:
    """Write a minimal-but-valid JPEG file."""
    path.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n"
        b"\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d"
        b"\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
        b"\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18\r\r\x182!\x1c!"
        b"22222222222222222222222222222222222222222222222222"
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03"
        b"\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t"
        b"\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05"
        b"\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
        b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16"
        b"\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz"
        b"\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99"
        b"\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7"
        b"\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5"
        b"\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1"
        b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03"
        b"\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01"
        b"\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02"
        b"\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02w\x00\x01\x02"
        b"\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13\"2\x81\x08\x14B\x91\xa1\xb1"
        b"\xc1\t#4R\xf0\x15br\x82\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
        b"STUVWXYZcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92"
        b"\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9"
        b"\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7"
        b"\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5"
        b"\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xa0\x0b\xf7\xff\xd9"
    )


class CQImageBuilderTests(unittest.TestCase):
    """Tests for the module-level CQ:image builder helpers."""

    def test_build_cq_image_file_produces_file_uri(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "test.jpg"
            _small_jpeg(img)
            cq = build_cq_image_file(str(img))
        self.assertIn("[CQ:image,file=", cq)
        self.assertIn("file:///", cq)
        self.assertIn("test.jpg", cq)

    def test_build_cq_image_base64_produces_base64_uri(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "test.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            cq = build_cq_image_base64(str(img))
        self.assertIn("[CQ:image,file=base64://", cq)
        self.assertIn("image/png", cq)
        # Verify it's decodable round-trip
        prefix = "[CQ:image,file=base64://"
        suffix_start = cq.index(prefix) + len(prefix)
        suffix_end = cq.rindex(",image/png]")
        b64_data = cq[suffix_start:suffix_end]
        decoded = base64.b64decode(b64_data)
        self.assertTrue(decoded.startswith(b"\x89PNG"))


class OneBotImageSendTests(unittest.TestCase):
    """Tests for OneBotClient.send_image() with fallback logic."""

    def setUp(self):
        self._old_config = config_module.config

    def tearDown(self):
        config_module.config = self._old_config

    def _client(self, **cfg_overrides):
        cfg = _fake_config(**cfg_overrides)
        config_module.config = cfg
        return OneBotClient(cfg)

    # ── non-existent file ──────────────────────────────────────────

    def test_missing_file_returns_false(self):
        client = self._client()
        result = client.send_image("123", "/nonexistent/file.jpg")
        self.assertFalse(result)

    # ── file URI succeeds ──────────────────────────────────────────

    def test_file_uri_success_returns_true_no_fallback(self):
        client = self._client()
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "cat.jpg"
            _small_jpeg(img)
            with patch.object(client, "_send_msg_and_catch", return_value=True) as mock_send:
                result = client.send_image("456", str(img), is_group=True)
        self.assertTrue(result)
        self.assertEqual(mock_send.call_count, 1)
        sent_msg = mock_send.call_args[0][1]
        self.assertIn("file:///", sent_msg)
        self.assertNotIn("base64://", sent_msg)

    # ── file URI fails → base64 fallback succeeds ─────────────────

    def test_file_uri_fails_base64_fallback_succeeds(self):
        client = self._client(image_send_base64_fallback=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "photo.jpg"
            _small_jpeg(img)
            with patch.object(client, "_send_msg_and_catch", side_effect=[False, True]) as mock_send:
                result = client.send_image("789", str(img))
        self.assertTrue(result)
        self.assertEqual(mock_send.call_count, 2)
        self.assertIn("file:///", mock_send.call_args_list[0][0][1])
        self.assertIn("base64://", mock_send.call_args_list[1][0][1])

    # ── file URI fails, base64 disabled ────────────────────────────

    def test_fallback_disabled_returns_false_after_file_fails(self):
        client = self._client(image_send_base64_fallback=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "pic.jpg"
            _small_jpeg(img)
            with patch.object(client, "_send_msg_and_catch", return_value=False) as mock_send:
                result = client.send_image("000", str(img))
        self.assertFalse(result)
        self.assertEqual(mock_send.call_count, 1)

    # ── file too large for base64 ──────────────────────────────────

    def test_file_too_large_skips_base64_fallback(self):
        client = self._client(image_send_base64_fallback=True, image_send_base64_max_mb=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "huge.jpg"
            img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * (2 * 1024 * 1024))
            with patch.object(client, "_send_msg_and_catch", return_value=False) as mock_send:
                result = client.send_image("111", str(img))
        self.assertFalse(result)
        self.assertEqual(mock_send.call_count, 1)

    # ── base64 logs size, not content ─────────────────────────────

    def test_base64_log_never_contains_raw_base64(self):
        """build_cq_image_base64 must not log the base64 string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir) / "logtest.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 200)
            with self.assertLogs("qq-bot", level="INFO") as log_ctx:
                cq = build_cq_image_base64(str(img))
            all_log_text = " ".join(log_ctx.output)
            self.assertNotIn(base64.b64encode(img.read_bytes()).decode("ascii"), all_log_text)
            # But length/size info should be present
            self.assertIn("base64_len=", all_log_text)


class PicAndImageCommandIntegrationTests(unittest.TestCase):
    """Verify /pic and /image use shared CQ builder helpers."""

    def test_pic_uses_build_cq_image_file(self):
        from src.commands.pic import build_cq_image_file as _f
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir).resolve() / "result.jpg"
            _small_jpeg(img)
            fake_result = SimpleNamespace(
                local_path=str(img),
                image_url="https://example.com/x.jpg",
                source_url="https://example.com",
                title="Test",
                description="",
                provider="tavily",
            )
            with patch("src.commands.pic.search_and_download_images", return_value=[fake_result]), \
                 patch("src.commands.pic.build_cq_image_file", wraps=_f) as mock_builder:
                ctx = SimpleNamespace(uid="123", session_key="private:123", raw_message="/pic test")
                # Need to swap config too
                with patch("src.commands.pic.config") as mock_cfg:
                    mock_cfg.image_search_enable = True
                    mock_cfg.image_search_send_max = 3
                    # re-resolve after patching
                    import src.commands.pic as pic_mod
                    reply = pic_mod.pic_reply("test", ctx)
            self.assertIn("[CQ:image,file=", reply)
            mock_builder.assert_called_once_with(str(img))

    def test_image_command_uses_build_cq_image_file(self):
        from src.commands.image import image_reply, build_cq_image_file as _f
        with tempfile.TemporaryDirectory() as tmpdir:
            img = Path(tmpdir).resolve() / "generated.jpg"
            _small_jpeg(img)
            fake_img = SimpleNamespace(path=str(img))
            with patch("src.commands.image.try_generate_image", return_value=([fake_img], "")), \
                 patch("src.commands.image.build_cq_image_file", wraps=_f) as mock_builder, \
                 patch("src.commands.image.config") as mock_cfg:
                mock_cfg.image_enable = True
                mock_cfg.image_admin_only = False
                mock_cfg.comfyui_workflow_api_path = str(img)
                mock_builder.return_value = f"[CQ:image,file={img.as_uri()}]"
                ctx = SimpleNamespace(uid="admin", session_key="private:admin", raw_message="/image test")
                reply = image_reply("test", ctx)
            self.assertIn("[CQ:image,file=", reply)
            mock_builder.assert_called_once_with(str(img))


if __name__ == "__main__":
    unittest.main()
