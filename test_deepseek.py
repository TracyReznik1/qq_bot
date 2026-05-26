import os

import requests
from dotenv import load_dotenv


load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY", "")
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
url = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
proxy_url = os.getenv("PROXY_URL", "")
proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

if not api_key:
    raise SystemExit("请先在 .env 里配置 DEEPSEEK_API_KEY")

response = requests.post(
    url,
    json={
        "model": model,
        "messages": [{"role": "user", "content": "用一句话回复：连接成功"}],
        "temperature": 0,
    },
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    proxies=proxies,
    timeout=20,
)
response.raise_for_status()
print(response.json()["choices"][0]["message"]["content"])
