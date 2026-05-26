# QQ 聊天机器人

这是一个基于 Flask + OneBot HTTP API + DeepSeek 的 QQ 机器人。

## 功能

- 私聊和群聊对话
- 群聊默认需要 @ 机器人
- 网页搜索后再回答
- 查询天气
- Pixiv 插画搜图并发送 CQ 图片
- 简单用户记忆
- DeepSeek、OneBot、代理、端口都从 `.env` 配置

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 配置

复制 `.env.example` 的内容到 `.env`，至少确认这些值：

```env
DEEPSEEK_API_KEY=sk-your-key-here
ONEBOT_API_URL=http://127.0.0.1:3000
PROXY_URL=http://127.0.0.1:7890
```

如果不需要代理，可以把 `PROXY_URL` 留空。

OneBot 端需要把 HTTP 事件上报地址设置为：

```text
http://127.0.0.1:5000/
```

## 启动

```powershell
python run_bot.py
```

浏览器打开下面地址可以检查机器人服务是否启动：

```text
http://127.0.0.1:5000/health
```

## 用法示例

```text
你好
查一下 DeepSeek 最新消息
北京天气
搜图 猫耳少女
记住 我喜欢简洁回答
帮助
```

## 文件说明

- `run_bot.py`：机器人主程序
- `test_deepseek.py`：DeepSeek 连通性测试
- `.env.example`：配置模板
- `ddy_data/memories`：用户记忆
- `ddy_data/img_history`：搜图历史
- `data_tmp`：临时图片文件
