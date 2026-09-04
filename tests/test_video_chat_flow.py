import unittest
from unittest.mock import MagicMock, patch

from src.chat import chat_service
from src.chat.chat_service import generate_reply, reset_history
from src.search.simple.models import SearchMode
from src.services.llm_types import ChatResponse
from src.services.video_service import BilibiliVideoPayload


class VideoChatFlowTests(unittest.TestCase):
    def setUp(self):
        reset_history("private:video_chat_user")

    def tearDown(self):
        reset_history("private:video_chat_user")

    @patch("src.chat.chat_service.get_simple_search_pipeline_for_chat")
    @patch("src.chat.chat_service.fetch_document")
    @patch("src.chat.chat_service.fetch_bilibili_video")
    def test_bilibili_url_in_chat_triggers_video_service_and_short_circuits_search(
        self,
        mock_fetch_video,
        mock_fetch_doc,
        mock_get_pipeline,
    ):
        mock_fetch_video.return_value = BilibiliVideoPayload(
            ok=True,
            status="success",
            bvid="BV1xx411c7mD",
            aid="170001",
            title="测试B站视频标题",
            owner_name="测试UP主",
            duration_seconds=300,
            pubdate_str="2024-01-01 12:00",
            desc="这是视频简介",
            part_title="P1 精彩内容",
            view_count=10000,
            like_count=500,
            has_subtitles=True,
            subtitles_text="00:00 大家好，今天给大家带来一个新技术的分享。\n01:30 这是核心概念。",
        )
        fake_llm = MagicMock()
        fake_llm.chat.return_value = ChatResponse(content="这个视频主要讲解了新技术。")

        with patch.object(chat_service, "llm", fake_llm):
            reply = generate_reply(
                "private:video_chat_user",
                "看下这个视频 https://www.bilibili.com/video/BV1xx411c7mD",
                mode=SearchMode.LIGHT,
            )

        self.assertEqual("这个视频主要讲解了新技术。", reply)
        # Bilibili video service called
        mock_fetch_video.assert_called_once_with(bvid="BV1xx411c7mD", aid="")
        # Standard doc fetch and search pipeline must NOT be called
        mock_fetch_doc.assert_not_called()
        mock_get_pipeline.assert_not_called()

        # Prompt payload passed to LLM contains external_bilibili_video sandbox
        called_messages = fake_llm.chat.call_args.args[0]
        untrusted_msg = called_messages[1]["content"]
        self.assertIn("<external_bilibili_video", untrusted_msg)
        self.assertIn("测试B站视频标题", untrusted_msg)
        self.assertIn("大家好，今天给大家带来一个新技术的分享", untrusted_msg)

        # History contains user message but NOT the video transcript
        history = chat_service.chat_history["private:video_chat_user"]
        user_history_entry = history[-2]["content"]
        self.assertIn("https://www.bilibili.com/video/BV1xx411c7mD", user_history_entry)
        self.assertNotIn("大家好，今天给大家带来一个新技术的分享", user_history_entry)

    @patch("src.chat.chat_service.get_simple_search_pipeline_for_chat")
    @patch("src.chat.chat_service.fetch_document")
    @patch("src.chat.chat_service.fetch_bilibili_video")
    def test_bilibili_bare_bv_in_chat_triggers_video_service(
        self,
        mock_fetch_video,
        mock_fetch_doc,
        mock_get_pipeline,
    ):
        mock_fetch_video.return_value = BilibiliVideoPayload(
            ok=True,
            status="success",
            bvid="BV1xx411c7mD",
            title="裸BV号视频",
            has_subtitles=False,
            subtitles_text="",
        )
        fake_llm = MagicMock()
        fake_llm.chat.return_value = ChatResponse(content="总结完毕。")

        with patch.object(chat_service, "llm", fake_llm):
            reply = generate_reply(
                "private:video_chat_user",
                "BV1xx411c7mD 这个视频讲了什么",
                mode=SearchMode.LIGHT,
            )

        self.assertEqual("总结完毕。", reply)
        mock_fetch_video.assert_called_once_with(bvid="BV1xx411c7mD", aid="")
        mock_fetch_doc.assert_not_called()
        mock_get_pipeline.assert_not_called()

    @patch("src.chat.chat_service.get_simple_search_pipeline_for_chat")
    @patch("src.chat.chat_service.fetch_document")
    @patch("src.chat.chat_service.fetch_bilibili_video")
    def test_bilibili_fetch_failure_falls_through_to_standard_flow(
        self,
        mock_fetch_video,
        mock_fetch_doc,
        mock_get_pipeline,
    ):
        mock_fetch_video.return_value = BilibiliVideoPayload(
            ok=False,
            status="video_not_found",
            error_message="视频不存在或已被删除",
        )
        fake_pipeline = MagicMock()
        fake_outcome = MagicMock()
        fake_outcome.failure = None
        fake_outcome.results = []
        fake_outcome.trace.answer_degraded = False
        fake_pipeline.run.return_value = fake_outcome
        mock_get_pipeline.return_value = fake_pipeline

        mock_fetch_doc.return_value = MagicMock(ok=False)

        fake_llm = MagicMock()
        fake_llm.chat.return_value = ChatResponse(content="普通搜索回答。")

        with patch.object(chat_service, "llm", fake_llm), \
             patch("src.chat.chat_service.SearchAnswerer") as mock_answerer_cls:
            mock_answerer = MagicMock()
            mock_answerer.answer.return_value = MagicMock(text="普通回答", degraded=False)
            mock_answerer_cls.return_value = mock_answerer

            reply = generate_reply(
                "private:video_chat_user",
                "https://www.bilibili.com/video/BV1xx411c7mD",
                mode=SearchMode.LIGHT,
            )

        # Video fetch was attempted
        mock_fetch_video.assert_called_once()
        # Because video fetch failed, fallback to doc fetch or search
        mock_fetch_doc.assert_called_once()
