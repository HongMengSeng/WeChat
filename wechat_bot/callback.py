"""回调 HTTP 服务：
- POST /callback   接收 gewechat 推送的消息
- GET  /files/<名>  文件服务（gewechat 容器拉取机器人要发送的图片时访问）
"""

import logging
import os

from flask import Flask, request, send_from_directory

log = logging.getLogger("bot.callback")


def create_app(bot) -> Flask:
    app = Flask(__name__)

    @app.post("/callback")
    def callback():
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return "success"
        # gewechat 注册回调时的连通性测试消息
        if "testMsg" in data:
            log.debug("收到回调测试消息")
            return "success"
        try:
            bot.dispatch(data)
        except Exception:
            log.exception("处理消息异常")
        return "success"

    @app.get("/files/<path:name>")
    def files(name: str):
        # 只允许访问媒体目录内的文件，防目录穿越
        name = os.path.basename(name)
        return send_from_directory(str(bot.cfg.media_dir), name)

    @app.get("/")
    def index():
        return "wechat-bot is running"

    return app


def run_app(app: Flask, port: int):
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
