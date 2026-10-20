"""入口：python -m wechat_bot.main"""

import logging
import os

from .bot import WeChatBot
from .config import load_config
from .logger import init_logging


def main():
    init_logging(os.environ.get("BOT_LOG_LEVEL", "INFO"))
    log = logging.getLogger("bot.main")
    cfg = load_config(os.environ.get("BOT_CONFIG", "config.yaml"))
    log.info("数据目录: %s", cfg.data_dir)
    bot = WeChatBot(cfg)
    bot.start()


if __name__ == "__main__":
    main()
