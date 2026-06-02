import json
import logging
import re
from typing import Any
from urllib.parse import quote

from src.config import config
from src.services.deepseek_client import DeepSeekClient
from src.services.search_service import web_search
from src.util import try_proxied_get


logger = logging.getLogger("qq-bot")

deepseek = DeepSeekClient(config)

WEATHER_EXTRACT_PROMPT = (
    "从用户输入中提取天气查询的城市和日期偏移量。严格按照 JSON 返回。\n"
    "\n"
    "字段规则：\n"
    "- city: 要查询的城市名，必须是标准中文名称（如\"北京\"、\"东京\"、\"纽约\"）。如果用户用了别名（如\"魔都\"→\"上海\"），请转为标准名。\n"
    "- day_offset: 整数，0=今天, 1=明天, 2=后天, 3=大后天, -1=周末/下周等超出范围\n"
    "- unsupported_reason: 如果 day_offset=-1，简要说明不支持的原因（如\"周末\"）；否则留空\n"
    "\n"
    "判断规则：\n"
    "1. 没指定城市 → city=\"\"\n"
    "2. 没指定日期 → day_offset=0\n"
    "3. \"大后天\" → day_offset=3\n"
    "4. \"周末\"、\"下周\"、\"未来几天\"等 → day_offset=-1\n"
    "5. 多个城市 → 只取第一个\n"
    "6. \"会不会下雨\"、\"热不热\"等属于对天气的询问，不影响 city 提取\n"
    "\n"
    "只返回 JSON，不要其他内容。\n"
    '格式示例：{"city": "北京", "day_offset": 1, "unsupported_reason": ""}'
)


def llm_extract_weather_params(text: str) -> dict[str, Any] | None:
    """用 LLM 从自然语言中提取城市和日期偏移量。失败返回 None。"""
    try:
        response = deepseek.chat(
            messages=[
                {"role": "system", "content": WEATHER_EXTRACT_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3]
        content = content.strip()
        result = json.loads(content)
        city = str(result.get("city", "")).strip()
        day_offset = int(result.get("day_offset", 0))
        unsupported_reason = str(result.get("unsupported_reason", "")).strip()
        return {
            "city": city,
            "day_offset": day_offset,
            "unsupported_reason": unsupported_reason,
        }
    except Exception:
        logger.debug("LLM weather extraction failed, falling back to rules")
        return None


def remove_command_words(text: str, words: list[str]) -> str:
    result = text
    for word in words:
        result = result.replace(word, " ")
    return re.sub(r"\s+", " ", result).strip(" ，。,.?？!！")


def extract_weather_city(text: str) -> str:
    city = remove_command_words(
        text,
        ["帮我", "查一下", "查询", "查查", "看看", "今天", "明天", "后天", "现在", "天气", "气温", "温度", "降雨", "下雨"],
    )
    city = re.sub(r"(会不会|怎么样|如何|多少|吗|呢|呀|啊)", " ", city)
    return re.sub(r"\s+", " ", city).strip(" ，。,.?？!！")


def extract_weather_day_offset(text: str) -> int:
    if "后天" in text:
        return 2
    if "明天" in text:
        return 1
    return 0


def is_generic_future_weather_request(text: str) -> bool:
    future_markers = ["未来", "接下来", "这几天", "这几日", "未来几天", "未来一周"]
    supported_day_markers = ["今天", "明天", "后天"]
    return any(marker in text for marker in future_markers) and not any(
        marker in text for marker in supported_day_markers
    )


def weather_day_label(day_offset: int) -> str:
    return {0: "今天", 1: "明天", 2: "后天"}.get(day_offset, f"{day_offset} 天后")


OPEN_METEO_WEATHER_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "大毛毛雨",
    56: "小冻毛毛雨",
    57: "大冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "小冻雨",
    67: "大冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def list_item(value: Any, index: int) -> Any:
    if isinstance(value, list) and 0 <= index < len(value):
        return value[index]
    return None


def format_location_name(location: dict[str, Any]) -> str:
    parts = [
        str(location.get("name") or "").strip(),
        str(location.get("admin1") or "").strip(),
        str(location.get("country") or "").strip(),
    ]
    return "，".join(part for part in parts if part)


def open_meteo_weather_lookup(city: str, day_offset: int = 0) -> str:
    geo_response = try_proxied_get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "zh", "format": "json"},
        proxies=config.proxies,
        timeout=config.request_timeout,
        headers={"User-Agent": "qq-bot-weather/1.0"},
    )
    geo_response.raise_for_status()
    geo_data = geo_response.json()
    locations = geo_data.get("results") or []
    if not locations:
        raise ValueError(f"Open-Meteo geocoding found no location for {city}")

    location = locations[0]
    latitude = location["latitude"]
    longitude = location["longitude"]
    forecast_response = try_proxied_get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": day_offset + 1,
            "timezone": location.get("timezone") or "auto",
        },
        proxies=config.proxies,
        timeout=config.request_timeout,
        headers={"User-Agent": "qq-bot-weather/1.0"},
    )
    forecast_response.raise_for_status()
    forecast = forecast_response.json()
    current = forecast["current"]
    daily = forecast.get("daily") or {}
    code = current.get("weather_code")
    desc = OPEN_METEO_WEATHER_CODES.get(int(code), "天气状况未知") if code is not None else "天气状况未知"
    location_name = format_location_name(location) or city

    min_temp = list_item(daily.get("temperature_2m_min"), day_offset)
    max_temp = list_item(daily.get("temperature_2m_max"), day_offset)
    rain_probability = list_item(daily.get("precipitation_probability_max"), day_offset)
    rain_text = f"，最高降水概率 {rain_probability}%" if rain_probability is not None else ""
    daily_text = f"{weather_day_label(day_offset)} {min_temp}~{max_temp}°C{rain_text}。" if min_temp is not None and max_temp is not None else ""

    if day_offset > 0:
        daily_code = list_item(daily.get("weather_code"), day_offset)
        daily_desc = OPEN_METEO_WEATHER_CODES.get(int(daily_code), "天气状况未知") if daily_code is not None else "天气状况未知"
        return f"{city}（{location_name}）{daily_text}{daily_desc}。".strip()

    return (
        f"{city}（{location_name}）现在 {current.get('temperature_2m')}°C，"
        f"体感 {current.get('apparent_temperature')}°C，{desc}，"
        f"湿度 {current.get('relative_humidity_2m')}%，风速 {current.get('wind_speed_10m')}km/h。\n"
        f"{daily_text}"
    ).strip()


def wttr_weather_lookup(city: str, day_offset: int = 0) -> str:
    url = f"https://wttr.in/{quote(city)}?format=j1&lang=zh"
    response = try_proxied_get(
        url,
        proxies=config.proxies,
        timeout=config.request_timeout,
        headers={"User-Agent": "qq-bot-weather/1.0"},
    )
    response.raise_for_status()
    data = response.json()
    current = data["current_condition"][0]
    today = data["weather"][day_offset]
    desc = current.get("lang_zh", current.get("weatherDesc", [{"value": ""}]))
    desc_text = desc[0].get("value", "") if isinstance(desc, list) and desc else str(desc)

    rain_chance = ""
    hourly = today.get("hourly") or []
    chances = [
        int(item.get("chanceofrain", 0))
        for item in hourly
        if str(item.get("chanceofrain", "")).isdigit()
    ]
    if chances:
        rain_chance = f"，最高降雨概率 {max(chances)}%"

    if day_offset > 0:
        return f"{city} {weather_day_label(day_offset)} {today.get('mintempC')}~{today.get('maxtempC')}°C{rain_chance}。"

    return (
        f"{city} 现在 {current.get('temp_C')}°C，体感 {current.get('FeelsLikeC')}°C，"
        f"{desc_text}，湿度 {current.get('humidity')}%，风速 {current.get('windspeedKmph')}km/h。\n"
        f"今天 {today.get('mintempC')}~{today.get('maxtempC')}°C{rain_chance}。"
    )


def weather_lookup(city: str, original_text: str) -> str:
    request_text = city or original_text
    full_request_text = f"{city} {original_text}"

    # 第一层：LLM 提取城市和日期
    params = llm_extract_weather_params(request_text)
    if params:
        city = params["city"]
        day_offset = params["day_offset"]

        if day_offset == -1:
            reason = params.get("unsupported_reason") or "这个日期"
            return f"我现在支持查今天、明天、后天（和大后天）的天气。{reason}暂时查不了。"

        if not city:
            return "想查哪里的天气？比如：/weather 北京。"

        return _call_weather_api(city, day_offset)

    # 第二层：规则兜底（LLM 不可用时）
    if is_generic_future_weather_request(full_request_text):
        return "我现在支持查今天、明天、后天的天气。你可以这样问：明天北京天气。"

    day_offset = extract_weather_day_offset(full_request_text)
    city = extract_weather_city(request_text)
    if not city:
        return "想查哪里的天气？比如：北京天气。"

    return _call_weather_api(city, day_offset)


def _call_weather_api(city: str, day_offset: int) -> str:
    """三级降级：Open-Meteo → wttr.in → 网页搜索。"""
    try:
        return open_meteo_weather_lookup(city, day_offset)
    except Exception:
        logger.exception("Open-Meteo weather lookup failed")

    try:
        return wttr_weather_lookup(city, day_offset)
    except Exception:
        logger.exception("wttr.in weather lookup failed")

    search_info = web_search(f"{city} {weather_day_label(day_offset)} 天气")
    return f"天气接口都没连上，我先按网页结果给你查：\n{search_info}"
