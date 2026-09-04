import unittest
from unittest import mock

from src.services import video_service
from src.services.video_service import (
    BilibiliUserPayload,
    BilibiliUserVideo,
    fetch_bilibili_user,
    format_bilibili_user_card,
)


class TestBiliUserService(unittest.TestCase):
    def setUp(self):
        video_service._cached_mixin_key = "ea1db124af3c281b47417b515f460577"
        video_service._cached_mixin_key_expire = 9999999999.0

    def tearDown(self):
        video_service._cached_mixin_key = ""
        video_service._cached_mixin_key_expire = 0.0

    def test_format_bilibili_user_card_full(self):
        payload = BilibiliUserPayload(
            ok=True,
            status="success",
            mid=946974,
            uname="影视飓风",
            usign="无限进步！",
            fans=17341273,
            videos=924,
            level=6,
            verify_info="bilibili 2024百大UP主",
            is_live=True,
            room_id=12345,
            recent_videos=(
                BilibiliUserVideo(bvid="BV1RJtt63EYn", title="动态视频｜混剪挑战赛"),
                BilibiliUserVideo(bvid="BV1Na4Q64Eos", title="去了一趟西班牙2.0"),
            ),
        )
        card = format_bilibili_user_card(payload)
        self.assertIn("【影视飓风】", card)
        self.assertIn("UID: 946974", card)
        self.assertIn("1734.1万", card)
        self.assertIn("924部", card)
        self.assertIn("bilibili 2024百大UP主", card)
        self.assertIn("无限进步！", card)
        self.assertIn("🔴 直播中 (房间号: 12345)", card)
        self.assertIn("BV1RJtt63EYn", card)
        self.assertIn("BV1Na4Q64Eos", card)
        self.assertIn("/video", card)

    def test_format_bilibili_user_card_not_live_and_small_fans(self):
        payload = BilibiliUserPayload(
            ok=True,
            status="success",
            mid=1001,
            uname="测试创作者",
            usign="",
            fans=850,
            videos=10,
            level=4,
            verify_info="",
            is_live=False,
            room_id=0,
            recent_videos=(),
        )
        card = format_bilibili_user_card(payload)
        self.assertIn("【测试创作者】", card)
        self.assertIn("850", card)
        self.assertIn("⚪ 未开播", card)

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_user_by_keyword_success(self, mock_get):
        resp = mock.MagicMock()
        resp.json.return_value = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "mid": 946974,
                        "uname": "影视飓风",
                        "usign": "无限进步！",
                        "fans": 17341273,
                        "videos": 924,
                        "level": 6,
                        "official_verify": {"desc": "2024百大UP主", "type": 0},
                        "is_live": 0,
                        "room_id": 0,
                        "res": [
                            {"bvid": "BV1RJtt63EYn", "title": "挑战赛视频"},
                        ],
                    }
                ]
            },
        }
        mock_get.return_value = resp

        payload = fetch_bilibili_user("影视飓风")
        self.assertTrue(payload.ok)
        self.assertEqual(payload.mid, 946974)
        self.assertEqual(payload.uname, "影视飓风")
        self.assertEqual(payload.fans, 17341273)
        self.assertEqual(payload.videos, 924)
        self.assertEqual(payload.verify_info, "2024百大UP主")
        self.assertEqual(len(payload.recent_videos), 1)
        self.assertEqual(payload.recent_videos[0].bvid, "BV1RJtt63EYn")

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_user_by_mid_success(self, mock_get):
        resp = mock.MagicMock()
        resp.json.return_value = {
            "code": 0,
            "data": {
                "card": {
                    "mid": "946974",
                    "name": "影视飓风",
                    "sign": "无限进步！",
                    "level_info": {"current_level": 6},
                    "official_verify": {"desc": "科技UP主"},
                },
                "follower": 17341292,
                "archive_count": 939,
            },
        }
        mock_get.return_value = resp

        payload = fetch_bilibili_user("946974")
        self.assertTrue(payload.ok)
        self.assertEqual(payload.mid, 946974)
        self.assertEqual(payload.uname, "影视飓风")
        self.assertEqual(payload.fans, 17341292)
        self.assertEqual(payload.videos, 939)

    @mock.patch("src.services.video_service.try_proxied_get")
    def test_fetch_bilibili_user_not_found(self, mock_get):
        resp = mock.MagicMock()
        resp.json.return_value = {
            "code": 0,
            "data": {
                "result": []
            },
        }
        mock_get.return_value = resp

        payload = fetch_bilibili_user("不存在的超级古怪UP主名称999")
        self.assertFalse(payload.ok)
        self.assertEqual(payload.status, "not_found")
        self.assertIn("未找到", payload.error_message)


if __name__ == "__main__":
    unittest.main()
