import unittest
from unittest import mock

from src.commands import CommandContext, handle_command
from src.router import Route
from src.services.video_service import BilibiliVideoPayload


class TestVideoCommand(unittest.TestCase):
    def test_video_command_empty_query(self):
        ctx = CommandContext(uid="1001", session_key="private:1001", raw_message="/video")
        route = Route(handler="command", action="command", query="", command="video")
        res = handle_command(route, ctx)
        self.assertTrue(res.handled)
        self.assertIn("想让我总结哪个B站视频", res.reply)

    def test_video_command_invalid_query(self):
        ctx = CommandContext(uid="1001", session_key="private:1001", raw_message="/video https://example.com")
        route = Route(handler="command", action="command", query="https://example.com", command="video")
        res = handle_command(route, ctx)
        self.assertTrue(res.handled)
        self.assertIn("没有识别到有效", res.reply)

    @mock.patch("src.commands.video.fetch_bilibili_video")
    @mock.patch("src.commands.video._plain_reply")
    def test_video_command_success(self, mock_reply, mock_fetch):
        mock_fetch.return_value = BilibiliVideoPayload(
            ok=True,
            status="success",
            bvid="BV1xx411c7mD",
            title="测试视频",
            owner_name="UP主",
            duration_seconds=60,
            desc="简介",
            has_subtitles=True,
            subtitles_text="[00:01] 字幕内容",
        )
        mock_reply.return_value = "这是视频总结：核心内容是..."

        ctx = CommandContext(uid="1001", session_key="private:1001", raw_message="/video BV1xx411c7mD")
        route = Route(handler="command", action="command", query="BV1xx411c7mD", command="video")
        res = handle_command(route, ctx)

        self.assertTrue(res.handled)
        self.assertEqual(res.reply, "这是视频总结：核心内容是...")
        mock_fetch.assert_called_once_with("BV1xx411c7mD")
        mock_reply.assert_called_once()

    def test_video_command_alias(self):
        ctx = CommandContext(uid="1001", session_key="private:1001", raw_message="/v")
        route = Route(handler="command", action="command", query="", command="v")
        res = handle_command(route, ctx)
        self.assertTrue(res.handled)
        self.assertIn("想让我总结哪个B站视频", res.reply)


if __name__ == "__main__":
    unittest.main()
