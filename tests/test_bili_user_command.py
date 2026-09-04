import unittest
from unittest.mock import MagicMock, patch

from src.commands import CommandContext, handle_command
from src.commands.bili_user import bili_user_reply
from src.memory.models import MemoryContext
from src.services.llm_types import ChatResponse
from src.services.video_service import BilibiliUserPayload, BilibiliUserVideo


class TestBiliUserCommand(unittest.TestCase):
    def setUp(self):
        self.context = CommandContext(
            uid="1001",
            session_key="private:test_user",
            raw_message="/up",
        )

    def test_bili_user_empty_query(self):
        reply = bili_user_reply("", self.context)
        self.assertIn("想查询哪位 B站 UP主？", reply)
        self.assertIn("/up", reply)

    @patch("src.commands.bili_user.fetch_bilibili_user")
    def test_bili_user_card_only(self, mock_fetch):
        mock_fetch.return_value = BilibiliUserPayload(
            ok=True,
            status="success",
            mid=946974,
            uname="影视飓风",
            usign="无限进步！",
            fans=17341273,
            videos=924,
            level=6,
            verify_info="2024百大UP主",
            is_live=False,
            room_id=0,
            recent_videos=(
                BilibiliUserVideo(bvid="BV1RJtt63EYn", title="挑战赛视频"),
            ),
        )
        fake_llm = MagicMock()
        with patch("src.chat.chat_service.llm", fake_llm):
            reply = bili_user_reply("影视飓风", self.context)

        # Returns card directly without calling LLM
        self.assertIn("【影视飓风】", reply)
        self.assertIn("1734.1万", reply)
        self.assertIn("BV1RJtt63EYn", reply)
        fake_llm.chat.assert_not_called()

    @patch("src.commands.bili_user._plain_reply")
    @patch("src.commands.bili_user.fetch_bilibili_user")
    def test_bili_user_with_question_calls_llm(self, mock_fetch, mock_plain_reply):
        mock_fetch.return_value = BilibiliUserPayload(
            ok=True,
            status="success",
            mid=946974,
            uname="影视飓风",
            usign="无限进步！",
            fans=17341273,
            videos=924,
            level=6,
            verify_info="2024百大UP主",
            is_live=False,
            room_id=0,
            recent_videos=(
                BilibiliUserVideo(bvid="BV1RJtt63EYn", title="挑战赛视频"),
            ),
        )
        mock_plain_reply.return_value = "影视飓风主要制作数码科技与摄影类视频。"

        reply = bili_user_reply("影视飓风 他主要是做什么内容的？", self.context)
        self.assertEqual("影视飓风主要制作数码科技与摄影类视频。", reply)
        mock_plain_reply.assert_called_once()
        call_kwargs = mock_plain_reply.call_args.kwargs
        self.assertIn("video_payload", call_kwargs)
        self.assertIn("影视飓风", call_kwargs["video_payload"])

    @patch("src.commands.bili_user.fetch_bilibili_user")
    def test_bili_user_not_found(self, mock_fetch):
        mock_fetch.return_value = BilibiliUserPayload(
            ok=False,
            status="not_found",
            error_message="未找到与 “不存在的UP” 相关的 B站 UP主。",
        )
        reply = bili_user_reply("不存在的UP", self.context)
        self.assertIn("未找到", reply)

    def test_command_routing_up_and_alias(self):
        from src.router import Route

        with patch("src.commands.bili_user.bili_user_reply") as mock_handler:
            mock_handler.return_value = "名片回复"
            route1 = Route(handler="command", action="command", query="影视飓风", command="up")
            res1 = handle_command(route1, self.context)
            self.assertTrue(res1.handled)
            self.assertEqual(res1.reply, "名片回复")

            route2 = Route(handler="command", action="command", query="影视飓风", command="biliup")
            res2 = handle_command(route2, self.context)
            self.assertTrue(res2.handled)
            self.assertEqual(res2.reply, "名片回复")


if __name__ == "__main__":
    unittest.main()
