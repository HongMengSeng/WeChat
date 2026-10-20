"""每群会话：对话历史 + 图片栈 + 图片指代解析 + 会话持久化"""

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger("bot.session")


@dataclass
class ImageRef:
    path: str          # 本地文件路径
    sender_wxid: str
    sender_name: str
    ts: float


class GroupSession:
    def __init__(self, room_id: str, history_n: int = 8, image_n: int = 20):
        self.room_id = room_id
        self.history = deque(maxlen=history_n)   # [(role, text), ...]
        self.images = deque(maxlen=image_n)      # [ImageRef, ...]
        # 群级模型覆盖（#模型 命令设置）
        self.model_override = ""
        self.vision_model_override = ""

    # ---------- 图片栈 ----------
    def add_image(self, path: str, sender_wxid: str, sender_name: str):
        self.images.append(ImageRef(path, sender_wxid, sender_name, time.time()))

    def find_images(self, text: str, sender_wxid: str = "",
                    pending_seconds: int = 180) -> list:
        """按用户消息解析图片指代，返回 [path, ...]"""
        items = list(self.images)
        if not items:
            return []
        t = text or ""

        # "这几张/这些图/全部图" → 最近 3 张
        if any(w in t for w in ("这几张", "这些图", "所有图", "全部图")):
            return [it.path for it in items[-3:]]

        # "第N张"（倒数）
        ordinals = {"上一张": 1, "上张": 1, "第二张": 2, "第2张": 2, "第三张": 3, "第3张": 3}
        for word, idx in ordinals.items():
            if word in t:
                return [items[-idx].path] if len(items) >= idx else []

        # "XX发的图" / "@XX 图" → 按发送者找其最新一张
        for it in reversed(items):
            if it.sender_name and it.sender_name in t:
                return [it.path]
            if "他发的" in t or "她发的" in t or "我发的" in t:
                if ("我" in t and it.sender_wxid == sender_wxid) or \
                   ("我" not in t):
                    return [it.path]

        # 泛指：这张/这图/这个图/图片/看看图/识别/分析
        if any(w in t for w in ("这张", "这图", "这个图", "刚才那张", "刚那张",
                                "图片", "识别", "看一下图", "看下图", "什么图")):
            return [items[-1].path]

        # 无显式指代：该用户 pending 时间窗内发过图 → 自动关联他最新的图
        now = time.time()
        for it in reversed(items):
            if it.sender_wxid == sender_wxid and now - it.ts <= pending_seconds:
                return [it.path]
        return []

    # ---------- 对话历史 ----------
    def add_turn(self, user_text: str, assistant_text: str):
        self.history.append(("user", user_text))
        self.history.append(("assistant", assistant_text))

    def history_messages(self) -> list:
        return [{"role": r, "content": c} for r, c in self.history]

    def reset(self):
        self.history.clear()
        self.images.clear()
        self.model_override = ""
        self.vision_model_override = ""


class SessionStore:
    """会话持久化到 data/sessions.json，重启不丢上下文"""

    def __init__(self, path: Path):
        self.path = path
        self._sessions: dict = {}

    def get(self, room_id: str, history_n: int, image_n: int) -> GroupSession:
        if room_id not in self._sessions:
            s = GroupSession(room_id, history_n, image_n)
            self._sessions[room_id] = s
            self._load_one(s)
        return self._sessions[room_id]

    def all_sessions(self) -> dict:
        return self._sessions

    def save(self):
        try:
            data = {}
            for rid, s in self._sessions.items():
                data[rid] = {
                    "history": list(s.history),
                    "images": [asdict(i) for i in s.images],
                    "model_override": s.model_override,
                    "vision_model_override": s.vision_model_override,
                }
            self.path.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            log.warning("会话保存失败: %s", e)

    def _load_one(self, s: GroupSession):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            d = data.get(s.room_id)
            if not d:
                return
            for role, text in d.get("history", []):
                s.history.append((role, text))
            for img in d.get("images", []):
                if Path(img["path"]).exists():
                    s.images.append(ImageRef(**img))
            s.model_override = d.get("model_override", "")
            s.vision_model_override = d.get("vision_model_override", "")
        except Exception as e:
            log.warning("会话加载失败 %s: %s", s.room_id, e)
