"""扫码登录：获取二维码 → 终端显示/存图 → 轮询直到登录成功"""

import io
import logging
import time

log = logging.getLogger("bot.login")

try:
    import qrcode
except ImportError:
    qrcode = None


def show_qr(url: str, save_path: str = ""):
    """终端打印 ASCII 二维码并存 PNG（无可选依赖时只打印链接）"""
    print(f"\n请用微信扫描二维码登录（或用手机浏览器打开链接）:\n{url}\n")
    if qrcode is None:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    if save_path:
        try:
            qr.make_image().save(save_path)
            print(f"二维码图片已保存: {save_path}")
        except Exception as e:
            log.warning("二维码存图失败: %s", e)


def ensure_login(client, cfg) -> str:
    """确保登录在线，返回 app_id（阻塞直到成功）"""
    runtime = cfg.load_runtime()
    app_id = runtime.get("app_id", "")

    if app_id and client.check_online(app_id):
        log.info("app_id %s 已在线，跳过扫码", app_id)
        return app_id

    qr_path = str(cfg.data_dir / "qrcode.png")
    uuid = ""
    while True:
        qr = client.get_login_qr(app_id)   # app_id 为空时 gewechat 会新建
        new_app_id = qr.get("appId") or app_id
        uuid = qr.get("uuid", "")
        if not new_app_id or not uuid:
            log.error("获取二维码失败: %s，5 秒后重试", qr)
            time.sleep(5)
            continue
        app_id = new_app_id
        show_qr(f"http://weixin.qq.com/x/{uuid}", qr_path)

        # 轮询扫码状态
        while True:
            st = client.check_login(app_id, uuid)
            expired = st.get("expiredTime", 99)
            status = st.get("status")
            if expired <= 5:
                log.info("二维码即将过期，重新获取…")
                break
            if status == 2:
                nick = st.get("nickName", "")
                cfg.save_runtime(app_id=app_id)
                log.info("登录成功！昵称: %s, app_id: %s（已保存）", nick, app_id)
                return app_id
            time.sleep(3)


def main():
    """独立扫码登录：python -m wechat_bot.login"""
    import os
    from .config import load_config
    from .gewe import GeweClient
    from .logger import init_logging

    init_logging("INFO")
    cfg = load_config(os.environ.get("BOT_CONFIG", "config.yaml"))
    gewe = cfg["gewechat"]
    runtime = cfg.load_runtime()
    client = GeweClient(gewe["api_url"], gewe["download_url"], runtime.get("token", ""))
    if not client.token:
        client.token = client.get_token()
        cfg.save_runtime(token=client.token)
    app_id = ensure_login(client, cfg)
    print(f"登录成功，app_id={app_id} 已保存到 {cfg.runtime_path}")


if __name__ == "__main__":
    main()
