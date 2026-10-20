# 微信多模态 AI 机器人（WeChat Multimodal AI Bot）

基于 [Gewechat](https://github.com/Devo919/Gewechat)（iPad 协议）的个人微信 AI 机器人，Docker 一键部署，支持：

- ✅ **扫码登录** —— 无需破解 PC 微信，服务器扫码即用
- ✅ **多人群聊** —— 群白名单、每个群独立会话上下文
- ✅ **@ 触发问答** —— 只有 @ 机器人才回复，回复自动 **@ 回提问者**
- ✅ **图片理解** —— 多模态视觉模型识别图片；群里图片自动进入「图片上下文」，@机器人时说"这张图 / 上一张 / 第2张 / XX发的图"即可引用
- ✅ **文件阅读** —— 群里发 PDF / Word / Excel / CSV / TXT，@机器人提问即可基于文件内容回答
- ✅ **实时监控** —— 全量群消息落库 SQLite，随时查询
- ✅ **多模型自定义** —— OpenAI 兼容协议，DeepSeek / 通义千问 / Kimi / 智谱 / OpenAI / Ollama 本地模型……任意搭配，`#模型` 命令随时切换

> ⚠️ **风险声明（务必阅读）**
> Gewechat 官方仓库已因法律原因**停止维护**，Docker 镜像目前仍可拉取但无保障。
> 所有非官方个人微信机器人协议均存在**账号风控/封禁风险**。请务必：
> 1. 使用**小号**，勿用主力微信；
> 2. 仅用于个人学习/小群娱乐，勿商用、勿群发营销；
> 3. 控制回复频率（内置限流可调）。
> 本项目消息接入层已做抽象，后续可替换为其他通道而不改业务代码。

---

## 架构

```
┌────────────────────────── 服务器（Docker Compose）──────────────────────────┐
│                                                                            │
│  gewechat 容器(2531/2532)          wechat-bot 容器(9919)         大模型 API  │
│  ┌──────────────────┐  消息回调   ┌──────────────────────┐ HTTPS ┌────────┐ │
│  │ iPad 协议服务     │ ─────────► │ callback  接收消息    │ ────► │ 多家    │ │
│  │ 扫码登录/收发消息  │ ◄───────── │ router    @检测/白名单 │ ◄──── │ OpenAI  │ │
│  │ 文件下载服务(2532)│  发消息/@   │ session  图片上下文栈  │       │ 兼容协议 │ │
│  └──────────────────┘            │ llm      模型路由     │       └────────┘ │
│                                  │ storage  SQLite 落库  │                  │
│                                  └──────────────────────┘                  │
└────────────────────────────────────────────────────────────────────────────┘
```

## 快速部署

### 1. 准备一台国内服务器

要求：能装 Docker；**与登录微信的常用手机在同一省份**（Gewechat 硬性要求，跨省易掉线）。1核2G 起步。

### 2. 上传代码并配置

```bash
git clone https://github.com/HongMengSeng/WeChat.git
cd WeChat
cp .env.example .env          # 填入你要用的模型 API Key（用哪行填哪行）
cp config.example.yaml config.yaml
vim config.yaml               # 选默认模型 / 视觉模型，按需改群配置
```

### 3. 启动

```bash
docker compose up -d --build
docker compose logs -f bot    # 观察日志，出现 ASCII 二维码后用手机微信扫码
```

扫码登录成功后日志会显示昵称。之后把机器人微信拉进目标群即可。

- 二维码过期会自动刷新重出，直到扫码成功。
- 下次重启**无需重新扫码**（`data/runtime.json` 保存了登录态）。
- 新设备登录后**次日凌晨会掉线一次**，重启容器并**用同一个 app_id**（runtime.json 里）重新扫码即可，此后可长期在线。

### 4. 验证

在群里 `@机器人 你好`，机器人应回复并 @ 你。
私聊机器人（`private_chat.enabled: true` 时）直接发消息即可测试。

## 使用示例

```
你：@机器人 帮我看看这张图            （上一条你刚发的图会被自动关联）
机器人：@你 这张图是……
─────────────────────────────
你：[发图A] [发图B]
你：@机器人 对比一下这几张图
机器人：@你 第一张……第二张……
─────────────────────────────
你：[发文件 报告.pdf]
你：@机器人 总结一下这个文件
机器人：@你 该报告主要……
─────────────────────────────
你：@机器人 #模型列表
你：@机器人 #模型 gpt-4o
你：@机器人 #视觉模型 glm-4v-plus
```

## 内置命令

在群里 @机器人 或私聊发送：

| 命令 | 说明 |
|---|---|
| `#帮助` | 查看命令列表 |
| `#模型列表` | 列出 config.yaml 里配置的所有模型 |
| `#模型 <名称>` | 切换本群文本模型（如 `#模型 deepseek-reasoner`） |
| `#视觉模型 <名称>` | 切换本群视觉模型 |
| `#重置` | 清空本群对话上下文与图片栈 |
| `#状态` | 查看当前模型、图片栈、消息统计 |

## 多模型配置说明

任何 **OpenAI 兼容** API 都能接入，在 `config.yaml` 的 `llm.providers` 下加一段即可：

```yaml
llm:
  default_model: "deepseek-chat"        # 纯文本对话用
  vision_model: "qwen-vl-max-latest"    # 消息带图片时自动切到这个
  providers:
    deepseek:
      base_url: "https://api.deepseek.com/v1"
      api_key: "${DEEPSEEK_API_KEY}"    # 从 .env 读取，不要写进仓库
      models: ["deepseek-chat", "deepseek-reasoner"]
    my_ollama:                          # 本地模型也行
      base_url: "http://host.docker.internal:11434/v1"
      api_key: "ollama"
      models: ["qwen2.5:14b"]
```

规则：
- 机器人回复带图片时自动使用 `vision_model`（可在群里用 `#视觉模型` 覆盖）
- 也可用 `provider:model` 显式指定，如 `#模型 dashscope:qwen-max`

## 图片上下文机制（重点）

1. 群里**任何人**发的图片都会被下载存档，并压入该群的**图片栈**（默认记最近 20 张，含发送者与时间）；
2. 当有人 **@机器人** 时，按以下优先级关联图片：
   - @ 机器人时**同时发了图** → 直接用这张；
   - 消息含指代词（这张图 / 这图 / 上一张 / 第2张 / 几张图 / **某人**发的图……）→ 从图片栈解析；
   - 该用户在 `image_pending_seconds`（默认 180s）内发过图 → 自动关联他最近的图；
3. 命中图片 → 请求自动切换到视觉模型。

## 监控群消息

所有群消息（含未 @ 机器人的）实时写入 `data/bot.db`（SQLite）：

```bash
sqlite3 data/bot.db "SELECT datetime(ts,'unixepoch','localtime'), sender_name, content
                     FROM messages WHERE room='12345678@chatroom' ORDER BY id DESC LIMIT 20;"
```

## 常用运维

```bash
docker compose logs -f bot                 # 看日志/重新出二维码
docker compose restart bot                 # 重启（一般不用重新扫码）
docker compose exec bot python -m wechat_bot.login   # 单独重新扫码登录
docker compose down && docker compose up -d
```

掉线时若配置了 `monitor.offline_webhook`，机器人会向该 URL POST 告警 JSON。

## 项目结构

```
WeChat/
├── config.example.yaml     # 配置模板（复制为 config.yaml）
├── .env.example            # API Key 模板（复制为 .env）
├── docker-compose.yml      # gewechat + bot 双容器编排
├── Dockerfile
└── wechat_bot/
    ├── main.py             # 入口：登录 → 注册回调 → 启动
    ├── login.py            # 独立扫码登录
    ├── config.py           # 配置加载（YAML + ${ENV} 替换）
    ├── bot.py              # 核心：消息路由 / @检测 / @回复 / 限流
    ├── callback.py         # 回调 HTTP 服务 + 发图文件服务
    ├── session.py          # 每群会话：对话历史 + 图片栈 + 指代解析
    ├── storage.py          # SQLite 消息落库（监控）
    ├── llm.py              # 多 Provider 模型路由（OpenAI 兼容）
    ├── files_extract.py    # PDF/Word/Excel/CSV/TXT 文本提取
    ├── commands.py         # #命令 系统
    └── gewe/
        ├── client.py       # Gewechat API 客户端
        └── message.py      # 消息解析（AddMsg → WxMessage）
```

## 已知限制 / Roadmap

- [ ] 语音消息识别（需 silk→mp3 转换 + ASR）
- [ ] 文件下载走 `downloadCdn`，不同 gewe 版本参数可能需微调（见 `gewe/client.py` 注释）
- [ ] 回复图片/文件（当前仅回复文本）
- [ ] Gewechat 停维后的替代通道适配（wcferry / 企业微信官方机器人）

## License

MIT
