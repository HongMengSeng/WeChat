"""机器人核心：消息路由 / @检测 / 图片上下文 / 限流 / 回复@"""

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import commands
from .callback import create_app, run_app
from .config import Config
from .files_extract import extract_text
from .gewe import GeweClient, WxMessage, parse_payload
from .llm import ModelRouter
from .login import ensure_login
from .session import SessionStore
from .storage import Storage

log = logging.getLogger("bot.core")


class WeChatBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        gewe = cfg["gewechat"]
        runtime = cfg.load_runtime()
        self.client = GeweClient(gewe["api_url"], gewe["download_url"], runtime.get("token", ""))
        self.router = ModelRouter(cfg["llm"])
        self.sessions = SessionStore(cfg.data_dir / "sessions.json")
        self.storage = Storage(str(cfg.data_dir / "bot.db"))
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="handler")
        self.bot_wxid = ""
        self._nick_cache = {}       # room -> {wxid: name}
        self._nick_cache_ts = {}    # room -> ts
        self._last_ask = {}         # user -> ts（限流）
        self._offline_alerted = False

    # ================= 启动 =================
    def start(self):
        # 1. token
        if not self.client.token:
            self.client.token = self.client.get_token()
            self.cfg.save_runtime(token=self.client.token)
        # 2. 扫码登录（阻塞）
        app_id = ensure_login(self.client, self.cfg)
        self.client.app_id = app_id
        # 3. 回调服务
        import threading
        app = create_app(self)
        threading.Thread(target=run_app, args=(app, int(self.cfg["gewechat"]["bot_port"])),
                         daemon=True, name="callback-server").start()
        time.sleep(3)
        # 4. 注册回调
        ret = self.client.set_callback(self.client.token, self.cfg["gewechat"]["callback_url"])
        if ret.get("ret") != 200:
            log.error("注册回调失败: %s", ret)
        else:
            log.info("回调已注册: %s", self.cfg["gewechat"]["callback_url"])
        # 5. 掉线监控
        threading.Thread(target=self._monitor_loop, daemon=True, name="monitor").start()

        log.info("机器人启动完成，等待消息…")
        threading.Event().wait()   # 阻塞主线程

    # ================= 消息入口 =================
    def dispatch(self, payload: dict):
        msg = parse_payload(payload)
        if msg.skip or msg.is_self:
            return
        self.bot_wxid = msg.bot_wxid or self.bot_wxid

        # 忽略过期消息（重启后 gewechat 可能重推历史）
        if msg.create_time < time.time() - int(self.cfg["security"]["ignore_older_seconds"]):
            return

        sender_name = self._lookup_nick(msg) or msg.sender_wxid
        msg.sender_name = sender_name

        # 落库（监控）：图片/文件存摘要而非原始 XML
        if self.cfg["monitor"].get("log_all_messages", True):
            content = msg.content
            if msg.kind == "image":
                content = "[图片]"
            elif msg.kind == "file":
                content = f"[文件 {msg.file_info.get('file_name', '')}]"
            elif msg.kind == "voice":
                content = "[语音]"
            elif msg.kind == "emoji":
                content = "[表情]"
            self.storage.log(msg.room_id, msg.sender_wxid, sender_name, msg.kind,
                             content, msg.msg_id, at_me=msg.at_me)

        sess = self.sessions.get(
            msg.room_id,
            int(self.cfg["groups"]["context_turns"]),
            int(self.cfg["groups"]["image_stack_size"]),
        )
        # 图片无论是否@都进图片栈（图片上下文的核心）
        if msg.kind == "image":
            path = self._download_image(msg)
            if path:
                sess.add_image(path, msg.sender_wxid, sender_name)

        if msg.is_group:
            if msg.at_me:
                self.executor.submit(self._safe_handle, msg, True)
        else:
            pc = self.cfg["private_chat"]
            if pc.get("enabled") and (not pc.get("allowlist") or msg.sender_wxid in pc["allowlist"]):
                self.executor.submit(self._safe_handle, msg, False)

    # ================= 处理回复 =================
    def _safe_handle(self, msg: WxMessage, is_group: bool):
        try:
            self._handle(msg, is_group)
        except Exception:
            log.exception("处理消息失败 room=%s", msg.room_id)
            try:
                self._reply(msg, is_group, "抱歉，我刚才出了点小差错，请稍后再试。")
            except Exception:
                pass

    def _handle(self, msg: WxMessage, is_group: bool):
        room_cfg = {}
        if is_group:
            allow = self.cfg["groups"].get("allowlist") or []
            if allow and msg.room_id not in allow:
                return
            room_cfg = (self.cfg["groups"].get("per_group") or {}).get(msg.room_id, {})

        # 限流：同一用户最小提问间隔
        cooldown = int(self.cfg["security"]["user_cooldown_seconds"])
        last = self._last_ask.get(msg.sender_wxid, 0)
        if time.time() - last < cooldown:
            log.info("用户 %s 触发限流，忽略", msg.sender_name)
            return
        self._last_ask[msg.sender_wxid] = time.time()

        sess = self.sessions.get(
            msg.room_id,
            int(self.cfg["groups"]["context_turns"]),
            int(self.cfg["groups"]["image_stack_size"]),
        )

        text = msg.content.strip()

        # 命令
        if commands.is_command(text):
            self._reply(msg, is_group, commands.handle(self, sess, msg, text))
            return

        # 组装图片上下文
        image_paths = []
        if msg.kind == "image":
            # @机器人时直接发图：用刚入栈的这张
            if sess.images:
                image_paths = [sess.images[-1].path]
            text = ""
        else:
            pending = int(self.cfg["groups"]["image_pending_seconds"])
            image_paths = sess.find_images(text, msg.sender_wxid, pending)

        # 文件内容提取
        if msg.kind == "file":
            file_path = self._download_file(msg)
            if file_path:
                extracted = extract_text(file_path)
                if extracted:
                    text += f"\n\n[用户发送了文件《{msg.file_info.get('file_name', '')}》，内容如下]\n{extracted}"
                else:
                    text += f"\n\n[用户发送了文件《{msg.file_info.get('file_name', '')}》，但内容无法解析]"
            else:
                text += "\n\n[用户发送了文件，但下载失败]"

        if not text and not image_paths:
            self._reply(msg, is_group, "请把问题说完哦～")
            return

        # 系统提示词（群覆盖 > 全局）
        system = room_cfg.get("system_prompt") or self.cfg["groups"]["system_prompt"]
        model = sess.model_override or room_cfg.get("default_model", "")
        vision_model = sess.vision_model_override or room_cfg.get("vision_model", "")

        history = sess.history_messages()
        # 历史里的图片不重复携带，当前消息携带图片即可
        prompt_text = text or "请描述这张图片"
        if msg.kind == "image":
            history_text = "[图片]"
        elif image_paths:
            history_text = f"{prompt_text}（附 {len(image_paths)} 张图片）"
        else:
            history_text = prompt_text

        reply = self.router.chat(system, history, prompt_text,
                                 model=model, image_paths=image_paths,
                                 vision_model=vision_model)

        # 截断保护
        max_len = int(self.cfg["security"]["max_reply_length"])
        if len(reply) > max_len:
            reply = reply[:max_len] + "\n…（内容过长已截断）"

        sess.add_turn(history_text, reply)
        self.sessions.save()
        self._reply(msg, is_group, reply)

    # ================= 发送 =================
    def _reply(self, msg: WxMessage, is_group: bool, text: str):
        if is_group:
            if self.cfg["groups"].get("reply_at", True) and msg.sender_wxid:
                content = f"@{msg.sender_name} {text}"
                self.client.post_text(msg.room_id, content, ats=msg.sender_wxid)
            else:
                self.client.post_text(msg.room_id, text)
        else:
            self.client.post_text(msg.room_id, text)
        # 模拟打字节奏，降低风控风险
        time.sleep(random.uniform(0.3, 1.2))

    # ================= 媒体 =================
    def _download_image(self, msg: WxMessage) -> str:
        """下载群图片，返回本地路径"""
        for img_type in (1, 2):   # 先高清，失败再普通
            try:
                data = self.client.download_image(msg.image_xml, img_type)
                path = self.cfg.media_dir / f"{msg.msg_id}.jpg"
                path.write_bytes(data)
                if self.cfg["monitor"].get("log_all_messages", True):
                    self.storage.log(msg.room_id, msg.sender_wxid, msg.sender_name,
                                     "image_saved", "[图片已存档]", msg.msg_id,
                                     media_path=str(path))
                return str(path)
            except Exception as e:
                log.warning("下载图片(type=%d)失败: %s", img_type, e)
        return ""

    def _download_file(self, msg: WxMessage) -> str:
        """下载群文件（downloadCdn 的 type 取值以部署版本文档为准，文件通常为 3）"""
        fi = msg.file_info
        try:
            data = self.client.download_cdn(
                fi.get("aes_key", ""), fi.get("file_id", ""), 3,
                int(fi.get("size", 0)), fi.get("suffix", "bin"),
            )
            suffix = fi.get("suffix", "bin").lstrip(".")
            path = self.cfg.media_dir / f"{msg.msg_id}.{suffix}"
            path.write_bytes(data)
            return str(path)
        except Exception as e:
            log.warning("下载文件失败 %s: %s", fi.get("file_name"), e)
            return ""

    # ================= 昵称解析 =================
    def _lookup_nick(self, msg: WxMessage) -> str:
        try:
            if not msg.is_group:
                infos = self.client.get_brief_info([msg.sender_wxid])
                return infos[0].get("nickName", "") if infos else ""
            cache = self._nick_cache.get(msg.room_id)
            now = time.time()
            if cache is None or now - self._nick_cache_ts.get(msg.room_id, 0) > 300:
                members = self.client.get_chatroom_member_list(msg.room_id)
                cache = {m["wxid"]: (m.get("displayName") or m.get("nickName") or m["wxid"])
                         for m in members}
                self._nick_cache[msg.room_id] = cache
                self._nick_cache_ts[msg.room_id] = now
            return cache.get(msg.sender_wxid, "")
        except Exception as e:
            log.warning("获取昵称失败: %s", e)
            return ""

    # ================= 掉线监控 =================
    def _monitor_loop(self):
        webhook = self.cfg["monitor"].get("offline_webhook", "")
        while True:
            time.sleep(60)
            try:
                online = self.client.check_online(self.client.app_id)
                if not online:
                    log.error("⚠️ 微信已掉线！重启容器或执行 python -m wechat_bot.login 重新扫码")
                    if webhook and not self._offline_alerted:
                        try:
                            requests.post(webhook, json={
                                "text": "微信机器人已掉线，请登录服务器重新扫码",
                            }, timeout=10)
                            self._offline_alerted = True
                        except Exception:
                            pass
                else:
                    self._offline_alerted = False
            except Exception as e:
                log.warning("在线检查失败: %s", e)
