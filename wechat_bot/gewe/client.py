"""Gewechat API 客户端

接口路径与参数对齐 dify-on-wechat 的 lib/gewechat 实现（v2/api）。
注意：downloadCdn 的 type 取值在不同 gewe 版本可能不同（文件通常为 3），
若群文件下载失败，可对照所部署 gewe 镜像的文档微调。
"""

import logging

import requests

log = logging.getLogger("bot.gewe")


class GeweError(Exception):
    pass


class GeweClient:
    def __init__(self, api_url: str, download_url: str, token: str = ""):
        self.api_url = api_url.rstrip("/")
        self.download_url = download_url.rstrip("/")
        self.token = token
        self.app_id = None

    # ---------- 基础 ----------
    def _post(self, path: str, params: dict, timeout: int = 30) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-GEWE-TOKEN"] = self.token
        resp = requests.post(self.api_url + path, json=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ret") != 200:
            log.warning("gewe API %s 返回异常: %s", path, data)
        return data

    # ---------- 登录 ----------
    def get_token(self) -> str:
        data = self._post("/tools/getTokenId", {})
        if data.get("ret") != 200:
            raise GeweError(f"获取 token 失败: {data}")
        self.token = data["data"]
        return self.token

    def set_callback(self, token: str, callback_url: str) -> dict:
        return self._post("/tools/setCallback", {"token": token, "callbackUrl": callback_url})

    def check_online(self, app_id: str) -> bool:
        data = self._post("/login/checkOnline", {"appId": app_id})
        return data.get("ret") == 200 and bool(data.get("data"))

    def get_login_qr(self, app_id: str) -> dict:
        """返回 data: {appId, uuid, qrCodeBase64?/qrCodeUrl?}"""
        data = self._post("/login/getLoginQrCode", {"appId": app_id})
        if data.get("ret") != 200:
            raise GeweError(f"获取登录二维码失败: {data}")
        return data["data"]

    def check_login(self, app_id: str, uuid: str) -> dict:
        """返回 data: {status, expiredTime, nickName?}；status==2 表示登录成功"""
        return self._post(
            "/login/checkLogin", {"appId": app_id, "uuid": uuid, "captchCode": ""}
        ).get("data", {})

    def logout(self, app_id: str) -> dict:
        return self._post("/login/logout", {"appId": app_id})

    # ---------- 发送 ----------
    def post_text(self, to_wxid: str, content: str, ats: str = "") -> dict:
        return self._post(
            "/message/postText",
            {"appId": self.app_id, "toWxid": to_wxid, "content": content, "ats": ats},
        )

    def post_image_url(self, to_wxid: str, img_url: str) -> dict:
        """imgUrl 需是 gewechat 容器可访问的 URL（用本服务 /files/ 提供）"""
        return self._post(
            "/message/postImage", {"appId": self.app_id, "toWxid": to_wxid, "imgUrl": img_url}
        )

    def post_file_url(self, to_wxid: str, file_url: str, file_name: str) -> dict:
        return self._post(
            "/message/postFile",
            {"appId": self.app_id, "toWxid": to_wxid, "fileUrl": file_url, "fileName": file_name},
        )

    # ---------- 下载 ----------
    def download_image(self, xml: str, img_type: int = 1) -> bytes:
        """按消息 XML 下载图片，type: 1=高清 2=普通"""
        data = self._post(
            "/message/downloadImage",
            {"appId": self.app_id, "xml": xml, "type": img_type},
            timeout=60,
        )
        if data.get("ret") != 200 or not data.get("data"):
            raise GeweError(f"下载图片失败: {data}")
        return self._fetch_file(data["data"]["fileUrl"])

    def download_cdn(self, aes_key: str, file_id: str, file_type: int,
                     total_size: int, suffix: str) -> bytes:
        """下载群文件（PDF/Word 等）。file_type: 1图 2视频 3文件（以部署版本文档为准）"""
        data = self._post(
            "/message/downloadCdn",
            {
                "appId": self.app_id,
                "aesKey": aes_key,
                "fileId": file_id,
                "type": file_type,
                "totalSize": total_size,
                "suffix": suffix,
            },
            timeout=120,
        )
        if data.get("ret") != 200 or not data.get("data"):
            raise GeweError(f"下载文件失败: {data}")
        return self._fetch_file(data["data"]["fileUrl"])

    def _fetch_file(self, file_url: str) -> bytes:
        """fileUrl 为相对路径，通过 gewechat 的 2532 文件服务获取"""
        if file_url.startswith("http"):
            url = file_url
        else:
            url = f"{self.download_url}/{file_url.lstrip('/')}"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    # ---------- 联系人 / 群 ----------
    def get_brief_info(self, wxids: list) -> list:
        data = self._post("/contacts/getBriefInfo", {"appId": self.app_id, "wxids": wxids})
        if data.get("ret") == 200:
            return data.get("data") or []
        return []

    def get_chatroom_member_list(self, chatroom_id: str) -> list:
        data = self._post(
            "/group/getChatroomMemberList", {"appId": self.app_id, "chatroomId": chatroom_id}
        )
        if data.get("ret") == 200:
            return (data.get("data") or {}).get("memberList") or []
        return []
