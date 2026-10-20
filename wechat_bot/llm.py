"""多 Provider 模型路由：OpenAI 兼容协议，任意多家自由组合

providers 配置：
    deepseek:
      base_url: https://api.deepseek.com/v1
      api_key: sk-xxx
      models: [deepseek-chat, ...]

模型解析规则：
  "deepseek-chat"          → 在所有 providers 里找包含它的第一家
  "dashscope:qwen-max"     → 显式指定 provider
"""

import logging
from openai import OpenAI

log = logging.getLogger("bot.llm")


class ModelRouter:
    def __init__(self, llm_cfg: dict):
        self.cfg = llm_cfg
        self.default_model = llm_cfg.get("default_model", "")
        self.vision_model = llm_cfg.get("vision_model", "")
        self.temperature = float(llm_cfg.get("temperature", 0.7))
        self.max_tokens = int(llm_cfg.get("max_tokens", 2000))
        self._providers = llm_cfg.get("providers", {}) or {}
        self._clients: dict = {}       # cache_key -> OpenAI 实例
        self._model_index: dict = {}   # model -> (provider_name, base_url, api_key)
        for pname, p in self._providers.items():
            for m in p.get("models", []):
                self._model_index.setdefault(m, (pname, p["base_url"], p.get("api_key", "")))

    def list_models(self) -> list:
        out = []
        for pname, p in self._providers.items():
            for m in p.get("models", []):
                out.append(f"{m}  ({pname})")
        return out

    def resolve(self, model: str):
        """返回 (client, model_name)"""
        explicit = ":" in model and not model.startswith(("http", "/"))
        if explicit:
            pname, m = model.split(":", 1)
            p = self._providers.get(pname)
            if not p:
                raise ValueError(f"未配置的 provider: {pname}")
            entry = (pname, p["base_url"], p.get("api_key", ""))
            model_name = m
        else:
            entry = self._model_index.get(model)
            if not entry:
                raise ValueError(f"模型 {model} 未在 providers 中配置")
            model_name = model
        cache_key = entry[1]
        if cache_key not in self._clients:
            self._clients[cache_key] = OpenAI(
                base_url=entry[1], api_key=entry[2] or "EMPTY", timeout=120
            )
        return self._clients[cache_key], model_name

    # ---------- 对话 ----------
    def chat(self, system: str, history: list, text: str,
             model: str = "", image_paths: list = None,
             vision_model: str = "") -> str:
        """发起对话。image_paths 非空时自动使用视觉模型。"""
        image_paths = image_paths or []
        if image_paths:
            model = vision_model or self.vision_model
        model = model or self.default_model
        client, model_name = self.resolve(model)

        content = [{"type": "text", "text": text or "请描述这张图片"}]
        for p in image_paths:
            b64 = base64.b64encode(Path(p).read_bytes()).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        messages = [{"role": "system", "content": system}, *history,
                    {"role": "user", "content": content if image_paths else text}]
        resp = client.chat.completions.create(
            model=model_name, messages=messages,
            temperature=self.temperature, max_tokens=self.max_tokens,
        )
        reply = resp.choices[0].message.content or ""
        log.info("LLM 响应完成 model=%s images=%d len=%d", model_name, len(image_paths), len(reply))
        return reply
