import unittest
from unittest import mock

from src.services import video_service
from src.services.video_service import (
    extract_bilibili_id,
    is_bilibili_video_url,
    fetch_bilibili_video,
    sign_wbi_params,
    BilibiliVideoPayload,
)


class TestVideoService(unittest.TestCase):
    def setUp(self):
        video_service._cached_mixin_key = "ea1db124af3c281b47417b515f460577"
        video_service._cached_mixin_key_expire = 9999999999.0

    def tearDown(self):
        video_service._cached_mixin_key = ""
        video_service._cached_mixin_key_expire = 0.0

    def test_sign_wbi_params(self):
        params = {"bvid": "BV1xx411c7mD"}
        signed = sign_wbi_params(params)
        self.assertIn("wts", signed)
        self.assertIn("w_rid", signed)
        self.assertEqual(signed["bvid"], "BV1xx411c7mD")

    def test_extract_bilibili_id_direct_bv(self):
        bvid, aid = extract_bilibili_id("BV1xx411c7mD")
        self.assertEqual(bvid, "BV1xx411c7mD")
        self.assertEqual(aid, "")

    def test_extract_bilibili_id_url(self):
        bvid, aid = extract_bilibili_id("https://www.bilibili.com/video/BV1Q541167Qg?spm_id_from=333.1007")
        self.assertEqual(bvid, "BV1Q541167Qg")
        self.assertEqual(aid, "")

    def test_extract_bilibili_id_av(self):
        bvid, aid = extract_bilibili_id("https://www.bilibili.com/video/av170001")
        self.assertEqual(bvid, "")
        self.assertEqual(aid, "170001")

    def test_is_bilibili_video_url(self):
        self.assertTrue(is_bilibili_video_url("https://www.bilibili.com/video/BV1xx411c7mD"))
        self.assertTrue(is_bilibili_video_url("https://b23.tv/BV1xx411c7mD"))
        self.assertTrue(is_bilibili_video_url("快看这个视频 BV1xx411c7mD 很有趣"))
        self.assertFalse(is_bilibili_video_url("https://www.bilibili.com/read/cv12345"))
        self.assertFalse(is_bilibili_video_url("https://example.com/test"))

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_video_success_with_subtitles(self, mock_get):
        # 1. View API response
        view_resp = mock.MagicMock()
        view_resp.json.return_value = {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mD",
                "aid": 123456,
                "title": "测试视频标题",
                "desc": "这是视频测试简介",
                "duration": 185,
                "pubdate": 1700000000,
                "owner": {"name": "测试UP主"},
                "stat": {"view": 10000, "like": 500},
                "pages": [{"cid": 999888, "part": "P1 第一讲"}],
            },
        }

        # 2. Player V2 API response
        player_resp = mock.MagicMock()
        player_resp.json.return_value = {
            "code": 0,
            "data": {
                "subtitle": {
                    "subtitles": [
                        {
                            "id": 1,
                            "lan": "zh-CN",
                            "lan_doc": "中文（简体）",
                            "subtitle_url": "//i0.hdslb.com/bfs/subtitles/test.json",
                        }
                    ]
                }
            },
        }

        # 3. Subtitle content JSON response
        sub_resp = mock.MagicMock()
        sub_resp.json.return_value = {
            "body": [
                {"from": 0.0, "to": 2.5, "content": "大家好，今天给大家带来"},
                {"from": 2.5, "to": 5.0, "content": "关于人工智能的最新分享。"},
            ]
        }

        mock_get.side_effect = [view_resp, player_resp, sub_resp]

        payload = fetch_bilibili_video("BV1xx411c7mD")
        self.assertTrue(payload.ok)
        self.assertEqual(payload.status, "success")
        self.assertEqual(payload.title, "测试视频标题")
        self.assertEqual(payload.owner_name, "测试UP主")
        self.assertEqual(payload.duration_seconds, 185)
        self.assertTrue(payload.has_subtitles)
        self.assertIn("大家好，今天给大家带来", payload.subtitles_text)
        self.assertIn("关于人工智能的最新分享。", payload.subtitles_text)

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_video_no_subtitles_fallback(self, mock_get):
        view_resp = mock.MagicMock()
        view_resp.json.return_value = {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mD",
                "aid": 123456,
                "title": "无字幕视频",
                "desc": "详细的简介内容，介绍了该视频的核心技术要点",
                "duration": 60,
                "owner": {"name": "UP主2"},
                "pages": [{"cid": 111222, "part": ""}],
            },
        }

        player_resp = mock.MagicMock()
        player_resp.json.return_value = {
            "code": 0,
            "data": {"subtitle": {"subtitles": []}},
        }

        mock_get.side_effect = [view_resp, player_resp]

        payload = fetch_bilibili_video("BV1xx411c7mD")
        self.assertTrue(payload.ok)
        self.assertEqual(payload.status, "success")
        self.assertFalse(payload.has_subtitles)
        self.assertEqual(payload.subtitles_text, "")
        self.assertEqual(payload.desc, "详细的简介内容，介绍了该视频的核心技术要点")

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_video_with_keyword_args(self, mock_get):
        view_resp = mock.MagicMock()
        view_resp.json.return_value = {
            "code": 0,
            "data": {
                "bvid": "BV1xx411c7mD",
                "aid": 123456,
                "title": "测试关键字参数",
                "desc": "简介",
                "duration": 60,
                "owner": {"name": "UP主"},
                "pages": [{"cid": 111222, "part": ""}],
            },
        }
        player_resp = mock.MagicMock()
        player_resp.json.return_value = {
            "code": 0,
            "data": {"subtitle": {"subtitles": []}},
        }
        mock_get.side_effect = [view_resp, player_resp]

        payload = fetch_bilibili_video(bvid="BV1xx411c7mD", aid="")
        self.assertTrue(payload.ok)
        self.assertEqual(payload.title, "测试关键字参数")


if __name__ == "__main__":
    unittest.main()
