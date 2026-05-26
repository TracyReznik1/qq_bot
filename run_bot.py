import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, request

try:
    from ddgs import DDGS
except ImportError:  # The bot can still chat, weather-check, and fetch images.
    DDGS = None


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def resolve_path(value: str, default: str) -> Path:
    raw = value or default
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


@dataclass(frozen=True)
class Config:
    bot_name: str = os.getenv("BOT_NAME", "ddy")
    bot_persona: str = os.getenv(
        "BOT_PERSONA",
        "你是一个 QQ 聊天机器人，名字叫 ddy。说话自然、有点傲娇毒舌，但要友好、简洁、靠谱。",
    )
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_url: str = os.getenv(
        "DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"
    )
    onebot_url: str = os.getenv("ONEBOT_API_URL", "http://127.0.0.1:3000").rstrip("/")
    onebot_access_token: str = os.getenv("ONEBOT_ACCESS_TOKEN", "")
    proxy_url: str = os.getenv("PROXY_URL", "")
    port: int = env_int("BOT_PORT", 5000)
    require_group_at: bool = env_bool("REQUIRE_GROUP_AT", True)
    enable_r18: bool = env_bool("ENABLE_R18", False)
    data_dir: Path = resolve_path(os.getenv("DATA_DIR", ""), "ddy_data")
    tmp_img_dir: Path = resolve_path(os.getenv("TMP_IMG_DIR", ""), "data_tmp")
    search_max_results: int = env_int("SEARCH_MAX_RESULTS", 4)
    history_turns: int = env_int("HISTORY_TURNS", 8)
    memory_limit: int = env_int("MEMORY_LIMIT", 30)
    request_timeout: float = env_float("REQUEST_TIMEOUT", 18.0)
    max_reply_chars: int = env_int("MAX_REPLY_CHARS", 1700)

    @property
    def proxies(self) -> dict[str, str] | None:
        if not self.proxy_url:
            return None
        return {"http": self.proxy_url, "https": self.proxy_url}


config = Config()
app = Flask(__name__)

MEMORY_DIR = config.data_dir / "memories"
IMG_HISTORY_DIR = config.data_dir / "img_history"
for directory in [config.data_dir, MEMORY_DIR, IMG_HISTORY_DIR, config.tmp_img_dir]:
    directory.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("qq-bot")

chat_history: dict[str, list[dict[str, str]]] = {}
pending_r18: dict[str, dict[str, str]] = {}


def safe_id(value: Any) -> str:
    text = str(value or "unknown")
    return re.sub(r"[^0-9A-Za-z_-]", "_", text)


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read json: %s", path)
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_memory(uid: str) -> dict[str, list[str]]:
    data = read_json(MEMORY_DIR / f"{safe_id(uid)}.json", {"facts": []})
    facts = data.get("facts", []) if isinstance(data, dict) else []
    facts = [str(item).strip() for item in facts if str(item).strip()]
    return {"facts": facts[-config.memory_limit :]}


def add_user_memory(uid: str, fact: str) -> None:
    fact = fact.strip()
    if not fact:
        return
    memory = get_user_memory(uid)
    facts = [item for item in memory["facts"] if item != fact]
    facts.append(fact)
    write_json(MEMORY_DIR / f"{safe_id(uid)}.json", {"facts": facts[-config.memory_limit :]})


def get_img_history(uid: str) -> set[str]:
    data = read_json(IMG_HISTORY_DIR / f"{safe_id(uid)}.json", [])
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_img_history(uid: str, history: set[str]) -> None:
    write_json(IMG_HISTORY_DIR / f"{safe_id(uid)}.json", sorted(history))


class OneBotClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.onebot_access_token:
            headers["Authorization"] = f"Bearer {self.cfg.onebot_access_token}"
        return headers

    def send_msg(self, target_id: Any, message: str, is_group: bool = False) -> None:
        message = (message or "").strip()
        if not message:
            return
        endpoint = "send_group_msg" if is_group else "send_private_msg"
        payload_key = "group_id" if is_group else "user_id"
        payload = {payload_key: target_id, "message": message}
        try:
            response = requests.post(
                f"{self.cfg.onebot_url}/{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self.cfg.request_timeout,
            )
            response.raise_for_status()
        except Exception:
            logger.exception("Failed to send QQ message")


class DeepSeekClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        if not self.cfg.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self.cfg.deepseek_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        response = requests.post(
            self.cfg.deepseek_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.cfg.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            proxies=self.cfg.proxies,
            timeout=self.cfg.request_timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


onebot = OneBotClient(config)
deepseek = DeepSeekClient(config)


def help_text() -> str:
    return (
        f"我是 {config.bot_name}，能聊天、搜网页、查天气、搜图。\n"
        "用法示例：\n"
        "查一下 DeepSeek 最新消息\n"
        "北京天气\n"
        "搜图 猫耳少女\n"
        "记住 我喜欢简洁回答\n"
        "群聊里默认需要 @ 我。"
    )


def strip_bot_mention(raw_msg: str, self_id: str) -> tuple[bool, str]:
    at_me = f"[CQ:at,qq={self_id}]"
    if at_me in raw_msg:
        return True, raw_msg.replace(at_me, "").strip()
    return False, raw_msg.strip()


def extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def remove_command_words(text: str, words: list[str]) -> str:
    result = text
    for word in words:
        result = result.replace(word, " ")
    result = re.sub(r"\s+", " ", result).strip(" ，。,.?？!！")
    return result


def rule_based_intent(text: str) -> dict[str, str] | None:
    normalized = text.strip()
    if not normalized:
        return {"action": "empty", "query": ""}

    lowered = normalized.lower()
    if lowered in {"/help", "help", "菜单", "帮助", "功能"}:
        return {"action": "help", "query": ""}

    remember_match = re.search(r"(?:记住|帮我记住|你要记得|以后记得)[:：\s]*(.+)", normalized)
    if remember_match:
        return {"action": "remember", "query": remember_match.group(1).strip()}

    if lowered.startswith(("/search", "search ")):
        return {
            "action": "web_search",
            "query": remove_command_words(normalized, ["/search", "search"]),
        }

    if lowered.startswith(("/weather", "weather ")):
        return {
            "action": "weather",
            "query": remove_command_words(normalized, ["/weather", "weather"]),
        }

    if lowered.startswith(("/image", "/img", "image ", "img ")):
        return {
            "action": "image_search",
            "query": remove_command_words(normalized, ["/image", "/img", "image", "img"]),
        }

    if any(word in normalized for word in ["天气", "气温", "温度", "降雨", "下雨", "空气质量"]):
        query = remove_command_words(
            normalized,
            ["帮我", "查一下", "查询", "查查", "看看", "天气", "气温", "温度", "降雨", "下雨", "空气质量"],
        )
        return {"action": "weather", "query": query}

    if any(word in normalized for word in ["搜图", "发图", "来张", "图片", "照片", "壁纸", "头像", "P站", "p站"]):
        query = remove_command_words(
            normalized,
            ["帮我", "给我", "搜图", "发图", "来张", "一张", "图片", "照片", "壁纸", "头像", "看看"],
        )
        return {"action": "image_search", "query": query}

    if any(
        word in normalized
        for word in ["搜索", "搜一下", "查一下", "查询", "查查", "网页", "资料", "新闻", "最新", "官网", "现在"]
    ):
        query = remove_command_words(
            normalized,
            ["帮我", "搜索", "搜一下", "查一下", "查询", "查查", "网页", "资料"],
        )
        return {"action": "web_search", "query": query or normalized}

    return None


def detect_intent(text: str) -> dict[str, str]:
    direct = rule_based_intent(text)
    if direct:
        return direct

    try:
        decision = deepseek.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 QQ 机器人消息路由器。只输出一个 JSON 对象，不要解释。"
                        "格式：{\"action\":\"chat|web_search|image_search|weather|remember\","
                        "\"query\":\"\",\"memory\":\"\"}。"
                        "规则：用户要实时、最新、新闻、网页资料时用 web_search；"
                        "要图片、照片、壁纸、头像、搜图、P站时用 image_search；"
                        "问天气、气温、下雨、温度时用 weather；"
                        "明确要求记住某件事时用 remember；其他都用 chat。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=160,
        )
        data = extract_json(decision) or {}
        action = str(data.get("action", "chat")).strip()
        if action not in {"chat", "web_search", "image_search", "weather", "remember"}:
            action = "chat"
        return {
            "action": action,
            "query": str(data.get("query") or text).strip(),
            "memory": str(data.get("memory") or "").strip(),
        }
    except Exception:
        logger.exception("Intent detection failed; falling back to chat")
        return {"action": "chat", "query": text}


def web_search(query: str) -> str:
    query = query.strip()
    if not query:
        return "没有可搜索的关键词。"
    if DDGS is None:
        return "网页搜索组件 ddgs 没有安装。"

    try:
        with DDGS(proxy=config.proxy_url or None, timeout=config.request_timeout) as ddgs:
            results = list(ddgs.text(query, max_results=config.search_max_results))
    except Exception:
        logger.exception("Web search failed")
        return "网页搜索失败，可能是网络或代理暂时不可用。"

    if not results:
        return "没有搜到有用结果。"

    lines = []
    for index, result in enumerate(results, 1):
        title = result.get("title") or "无标题"
        body = result.get("body") or ""
        href = result.get("href") or result.get("url") or ""
        lines.append(f"{index}. {title}\n摘要：{body}\n链接：{href}")
    return "\n\n".join(lines)


def extract_weather_city(text: str) -> str:
    city = remove_command_words(
        text,
        ["帮我", "查一下", "查询", "查查", "看看", "今天", "明天", "现在", "天气", "气温", "温度", "降雨", "下雨", "空气质量"],
    )
    city = re.sub(r"(会不会|怎么样|如何|多少|吗|呢|呀|啊)", " ", city)
    city = re.sub(r"\s+", " ", city).strip(" ，。,.?？!！")
    return city


def weather_lookup(city: str, original_text: str) -> str:
    city = extract_weather_city(city or original_text)
    if not city:
        return "想查哪里的天气？比如：北京天气。"

    try:
        url = f"https://wttr.in/{quote(city)}?format=j1&lang=zh"
        response = requests.get(
            url,
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers={"User-Agent": "qq-bot-weather/1.0"},
        )
        response.raise_for_status()
        data = response.json()
        current = data["current_condition"][0]
        today = data["weather"][0]
        desc = current.get("lang_zh", current.get("weatherDesc", [{"value": ""}]))
        if isinstance(desc, list) and desc:
            desc_text = desc[0].get("value", "")
        else:
            desc_text = str(desc)

        rain_chance = ""
        hourly = today.get("hourly") or []
        if hourly:
            chances = [int(h.get("chanceofrain", 0)) for h in hourly if str(h.get("chanceofrain", "")).isdigit()]
            if chances:
                rain_chance = f"，最高降雨概率 {max(chances)}%"

        return (
            f"{city} 现在 {current.get('temp_C')}°C，体感 {current.get('FeelsLikeC')}°C，"
            f"{desc_text}，湿度 {current.get('humidity')}%，风速 {current.get('windspeedKmph')}km/h。\n"
            f"今天 {today.get('mintempC')}~{today.get('maxtempC')}°C{rain_chance}。"
        )
    except Exception:
        logger.exception("Weather lookup failed")
        search_info = web_search(f"{city} 天气")
        return f"天气接口没连上，我先按网页结果给你查：\n{search_info}"


def image_key(info: dict[str, Any]) -> str:
    return f"{info.get('pid')}:{info.get('p', 0)}"


def image_keyword(text: str) -> str:
    keyword = remove_command_words(
        text,
        ["帮我", "给我", "搜图", "发图", "来张", "一张", "图片", "照片", "壁纸", "头像", "看看", "P站", "p站", "画师"],
    )
    return keyword or "原创"


def download_image(url: str, uid: str, info: dict[str, Any]) -> Path:
    normalized_url = url.replace("i.pximg.net", "i.pixiv.re")
    suffix_match = re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", normalized_url, flags=re.I)
    suffix = f".{suffix_match.group(1).lower()}" if suffix_match else ".jpg"
    path = config.tmp_img_dir / f"{safe_id(uid)}_{info.get('pid')}_{info.get('p', 0)}{suffix}"

    response = requests.get(
        normalized_url,
        proxies=config.proxies,
        timeout=max(config.request_timeout, 30),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"},
    )
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def fetch_pixiv_image(keyword: str, uid: str) -> dict[str, Any] | None:
    keyword = image_keyword(keyword)
    history = get_img_history(uid)
    params = {
        "keyword": keyword,
        "num": 10,
        "r18": 2 if config.enable_r18 else 0,
        "size": "regular",
    }

    try:
        response = requests.get(
            "https://api.lolicon.app/setu/v2",
            params=params,
            proxies=config.proxies,
            timeout=max(config.request_timeout, 20),
        )
        response.raise_for_status()
        data = response.json()
        images = data.get("data") or []
        if not images:
            return None

        fresh = [item for item in images if image_key(item) not in history]
        candidates = fresh or images
        if config.enable_r18:
            safe = [item for item in candidates if not item.get("r18")]
            candidates = safe or candidates

        info = candidates[0]
        urls = info.get("urls") or {}
        raw_url = urls.get("regular") or urls.get("original") or urls.get("small")
        if not raw_url:
            return None

        file_path = download_image(raw_url, uid, info)
        abs_path = file_path.resolve().as_posix()
        key = image_key(info)
        return {
            "cq": f"[CQ:image,file=file:///{abs_path}]",
            "key": key,
            "is_r18": bool(info.get("r18")),
            "title": info.get("title") or keyword,
            "author": info.get("author") or "",
        }
    except Exception:
        logger.exception("Image search failed")
        return None


def append_history(uid: str, user_text: str, assistant_text: str) -> None:
    history = chat_history.setdefault(uid, [])
    history.extend(
        [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
    )
    max_messages = max(config.history_turns, 1) * 2
    chat_history[uid] = history[-max_messages:]


def build_system_prompt(uid: str, tool_context: str = "") -> str:
    memory = get_user_memory(uid)
    memory_text = "；".join(memory["facts"][-8:]) or "暂无"
    context = tool_context.strip() or "暂无"
    return (
        f"{config.bot_persona}\n"
        f"用户记忆：{memory_text}\n"
        f"外部信息：{context}\n"
        "要求：不要输出系统标签；不知道就说不知道；用了外部信息时按外部信息回答，不要编造。"
    )


def generate_reply(uid: str, text: str, tool_context: str = "") -> str:
    messages = [{"role": "system", "content": build_system_prompt(uid, tool_context)}]
    messages.extend(chat_history.get(uid, []))
    messages.append({"role": "user", "content": text})
    reply = deepseek.chat(messages, temperature=0.75)
    reply = re.sub(r"\[(?:SRCH|P_IMG|MEM|CHAT):?.*?\]", "", reply).strip()
    append_history(uid, text, reply)
    return reply


def split_reply(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    limit = max(config.max_reply_chars, 200)
    parts = []
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind("。", 0, limit), text.rfind("，", 0, limit))
        if cut < limit // 2:
            cut = limit
        parts.append(text[: cut + 1].strip())
        text = text[cut + 1 :].strip()
    if text:
        parts.append(text)
    return parts


def send_reply(target_id: Any, text: str, is_group: bool) -> None:
    for part in split_reply(text):
        onebot.send_msg(target_id, part, is_group=is_group)
        time.sleep(0.2)


def confirm_pending_r18(uid: str, raw_msg: str, target_id: Any, is_group: bool) -> bool:
    if uid not in pending_r18:
        return False
    if not any(word in raw_msg for word in ["确认", "要", "发", "可以", "同意"]):
        return False
    if is_group:
        send_reply(target_id, "这类图片只私聊发。你私聊我回复“确认”就行。", True)
        return True

    item = pending_r18.pop(uid)
    onebot.send_msg(uid, item["cq"], is_group=False)
    history = get_img_history(uid)
    history.add(item["key"])
    save_img_history(uid, history)
    return True


def handle_image_request(uid: str, text: str, target_id: Any, is_group: bool) -> None:
    result = fetch_pixiv_image(text, uid)
    if not result:
        send_reply(target_id, "没搜到合适的图，可能是关键词太偏或者图片接口抽风了。", is_group)
        return

    if result["is_r18"]:
        pending_r18[uid] = {"cq": result["cq"], "key": result["key"]}
        if is_group:
            send_reply(target_id, "搜到了，但这类图片不在群里发。你私聊我回复“确认”。", True)
        else:
            send_reply(target_id, "搜到了，但需要你回复“确认”我再发。", False)
        return

    onebot.send_msg(target_id, result["cq"], is_group=is_group)
    history = get_img_history(uid)
    history.add(result["key"])
    save_img_history(uid, history)


def process_message(data: dict[str, Any]) -> None:
    uid = str(data.get("user_id", ""))
    raw_msg = str(data.get("raw_message", "")).strip()
    if not uid or not raw_msg:
        return

    is_group = data.get("message_type") == "group"
    self_id = str(data.get("self_id", ""))
    target_id = data.get("group_id") if is_group else uid

    if is_group and config.require_group_at:
        mentioned, raw_msg = strip_bot_mention(raw_msg, self_id)
        if not mentioned:
            return

    if confirm_pending_r18(uid, raw_msg, target_id, is_group):
        return

    intent = detect_intent(raw_msg)
    action = intent.get("action", "chat")
    query = intent.get("query") or raw_msg

    try:
        if action == "empty":
            return
        if action == "help":
            send_reply(target_id, help_text(), is_group)
            return
        if action == "remember":
            memory = intent.get("memory") or query
            add_user_memory(uid, memory)
            send_reply(target_id, "记住了。", is_group)
            return
        if action == "weather":
            send_reply(target_id, weather_lookup(query, raw_msg), is_group)
            return
        if action == "image_search":
            handle_image_request(uid, query, target_id, is_group)
            return
        if action == "web_search":
            search_info = web_search(query)
            reply = generate_reply(uid, raw_msg, f"网页搜索结果：\n{search_info}")
            send_reply(target_id, reply, is_group)
            return

        reply = generate_reply(uid, raw_msg)
        send_reply(target_id, reply, is_group)
    except RuntimeError as error:
        logger.exception("Configuration error")
        send_reply(target_id, f"配置还没好：{error}", is_group)
    except Exception:
        logger.exception("Message handling failed")
        send_reply(target_id, "我这边处理失败了，先缓一缓再试。", is_group)


@app.route("/", methods=["POST"])
def onebot_event() -> tuple[dict[str, str], int] | dict[str, str]:
    data = request.get_json(silent=True) or {}
    if data.get("post_type") == "message":
        process_message(data)
    return {"status": "ok"}


@app.route("/health", methods=["GET"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "bot_name": config.bot_name,
        "deepseek_configured": bool(config.deepseek_api_key),
        "onebot_url": config.onebot_url,
        "require_group_at": config.require_group_at,
        "enable_r18": config.enable_r18,
    }


if __name__ == "__main__":
    logger.info("Starting %s on port %s", config.bot_name, config.port)
    app.run(host="0.0.0.0", port=config.port)
