"""日志初始化"""

import logging
import sys


def init_logging(level: str = "INFO"):
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    for noisy in ("werkzeug", "urllib3", "openai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
