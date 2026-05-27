import unittest

import router
import run_bot
import src.commands as commands
from src.commands import weather


class WeatherIntentTests(unittest.TestCase):
    def test_plain_weather_text_uses_chat_route(self) -> None:
        route = router.route_message("北京天气")

        self.assertEqual(route.handler, "chat")
        self.assertEqual(route.action, "chat")

    def test_weather_command_uses_weather_route(self) -> None:
        route = router.route_message("/weather 北京")

        self.assertEqual(route.handler, "command")
        self.assertEqual(route.action, "command")
        self.assertEqual(route.command, "weather")
        self.assertEqual(route.query, "北京")

    def test_command_module_handles_weather_command(self) -> None:
        self.assertTrue(hasattr(commands, "CommandContext"))
        self.assertTrue(hasattr(commands, "handle_command"))

        original_weather_lookup = weather.weather_lookup
        try:
            weather.weather_lookup = lambda query, original_text: f"{query}|{original_text}"

            result = commands.handle_command(
                router.route_message("/weather 北京"),
                commands.CommandContext(uid="123", session_key="private:123", raw_message="/weather 北京"),
            )

            self.assertTrue(result.handled)
            self.assertEqual(result.reply, "北京|/weather 北京")
        finally:
            weather.weather_lookup = original_weather_lookup


class WeatherDateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_open_meteo = weather.open_meteo_weather_lookup
        self.original_wttr = weather.wttr_weather_lookup
        self.original_web_search = weather.web_search

    def tearDown(self) -> None:
        weather.open_meteo_weather_lookup = self.original_open_meteo
        weather.wttr_weather_lookup = self.original_wttr
        weather.web_search = self.original_web_search

    def test_tomorrow_weather_uses_tomorrow_forecast(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_open_meteo(city: str, day_offset: int = 0) -> str:
            calls.append((city, day_offset))
            return f"{city}:{day_offset}"

        weather.open_meteo_weather_lookup = fake_open_meteo

        result = weather.weather_lookup("明天北京", "明天北京天气")

        self.assertEqual(result, "北京:1")
        self.assertEqual(calls, [("北京", 1)])

    def test_generic_future_weather_asks_for_supported_day(self) -> None:
        weather.open_meteo_weather_lookup = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no weather"))
        weather.wttr_weather_lookup = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no weather"))
        weather.web_search = lambda _query: "搜索兜底"

        result = weather.weather_lookup("未来北京", "未来北京天气")

        self.assertIn("今天、明天、后天", result)


if __name__ == "__main__":
    unittest.main()
