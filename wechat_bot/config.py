"""配置加载：YAML + ${ENV} 环境变量替换 + 运行时状态(runtime.json)"""

import os
import re
import json
import logging
from pathlib import Path

import yaml

log = logging.getLogger("bot.config")

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULTS = {
    "gewechat": {
        "api_url": "http://gewechat:2531/v2/api",
        "download_url": "http://gewechat:2532",
        "callback_url": "http://bot:9919/callback",
        "bot_port": 9919,
    },
    "llm": {
        "default_model": "deepseek-chat",
        "vision_model": "qwen-vl-max-latest",
        "temperature": 0.7,
        "max_tokens": 2000,
        "providers": {},
    },
    "groups": {
        "allowlist": [],
        "context_turns": 8,
        "image_stack_size": 20,
        "image_pending_seconds": 180,
        "reply_at": True,
        "system_prompt": "你是一个微信群里的 AI 助手，回答简洁口语化，不超过300字。",
        "per_group": {},
    },
    "private_chat": {"enabled": True, "allowlist": []},
    "security": {
        "admins": [],
        "user_cooldown_seconds": 5,
        "max_reply_length": 2000,
        "ignore_older_seconds": 120,
    },
    "media": {"data_dir": "data"},
    "monitor": {"log_all_messages": True, "offline_webhook": ""},
}


def _substitute_env(obj):
    """递归替换 ${VAR} 为环境变量值"""
    if isinstance(obj, dict):
        return {k: _substitute_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_env(v) for v in obj]
    if isinstance(obj, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, raw: dict, base_dir: Path):
        self._raw = raw
        self.base_dir = base_dir
        self.data_dir = base_dir / raw.get("media", {}).get("data_dir", "data")
        self.media_dir = self.data_dir / "media"
        self.runtime_path = self.data_dir / "runtime.json"
        for d in (self.data_dir, self.media_dir):
            d.mkdir(parents=True, exist_ok=True)

    def __getitem__(self, key):
        return self._raw.get(key, DEFAULTS.get(key, {}))

    def get(self, key, default=None):
        return self._raw.get(key, DEFAULTS.get(key, default))

    # ---- 运行时状态（app_id / token 持久化） ----
    def load_runtime(self) -> dict:
        if self.runtime_path.exists():
            try:
                return json.loads(self.runtime_path.read_text())
            except Exception:
                pass
        return {}

    def save_runtime(self, **kv):
        data = self.load_runtime()
        data.update(kv)
        self.runtime_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def load_config(config_path: str = "config.yaml") -> Config:
    base_dir = Path(config_path).resolve().parent
    path = Path(config_path)
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = _substitute_env(raw)
        raw = _deep_merge(DEFAULTS, raw)
        log.info("配置已加载: %s", path)
    else:
        log.warning("未找到 %s，使用默认配置", config_path)
        raw = dict(DEFAULTS)
    return Config(raw, base_dir)
