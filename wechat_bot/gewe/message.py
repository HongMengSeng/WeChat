"""消息解析：gewechat 回调 payload → WxMessage

群聊 payload 结构（关键部分）：
{
  "TypeName": "AddMsg",
  "Appid": "wx_xxx",
  "Wxid": "机器人wxid",
  "Data": {
    "MsgId": 585326344,
    "FromUserName": {"string": "xxx@chatroom"},
    "ToUserName":   {"string": "wxid_bot"},
    "MsgType": 1,
    "Content": {"string": "wxid_sender:\n@机器人名 你好"},
    "CreateTime": 1733447040,
    "MsgSource": "<msgsource><atuserlist><![CDATA[,wxid_bot]]></atuserlist></msgsource>",
    "PushContent": "xxx在群聊中@了你",
    "NewMsgId": 8449132831264840264
  }
}
"""

import re
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

log = logging.getLogger("bot.msg")

_ATUSERLIST_RE = re.compile(r"<atuserlist><!\[CDATA\[(.*?)\]\]>", re.S)
# 微信 @ 前缀以 U+2005（四分之一空格）结尾
_AT_MENTION_RE = re.compile(r"@[^ ]+ ")


@dataclass
class WxMessage:
    msg_id: int = 0
    msg_type: int = 0
    kind: str = "other"          # text/image/file/quote/share/voice/emoji/system/other
    is_group: bool = False
    is_self: bool = False
    at_me: bool = False
    room_id: str = ""            # 群 ID（is_group 时）
    sender_wxid: str = ""
    sender_name: str = ""        # 由 bot 层填充（查群成员列表）
    content: str = ""            # 清洗后的正文（去发送者前缀、去@前缀）
    raw_content: str = ""
    create_time: int = 0
    bot_wxid: str = ""
    # 附加信息
    image_xml: str = ""          # MsgType=3 时的图片 XML（用于下载）
    file_info: dict = field(default_factory=dict)   # MsgType=49 type=6 文件信息
    quote: dict = field(default_factory=dict)       # MsgType=49 type=57 引用信息
    skip: bool = False           # True=不需要处理（系统消息/状态同步等）


def _xml_find_text(root, path: str) -> str:
    node = root.find(path)
    return node.text.strip() if node is not None and node.text else ""


def parse_payload(payload: dict) -> WxMessage:
    msg = WxMessage()
    if not isinstance(payload, dict) or payload.get("TypeName") != "AddMsg":
        msg.skip = True
        return msg

    data = payload.get("Data") or payload.get("data") or {}
    if "NewMsgId" not in data or "FromUserName" not in data:
        msg.skip = True
        return msg

    bot_wxid = payload.get("Wxid", "")
    msg.bot_wxid = bot_wxid
    msg.msg_id = data.get("NewMsgId", 0)
    msg.msg_type = data.get("MsgType", 0)
    msg.create_time = int(data.get("CreateTime", 0))
    from_id = (data.get("FromUserName") or {}).get("string", "")
    msg.raw_content = (data.get("Content") or {}).get("string", "")
    msg.is_group = "@chatroom" in from_id
    msg.is_self = from_id == bot_wxid

    # 非用户账号（公众号等）
    msg_source = data.get("MsgSource", "") or ""
    if from_id in ("Tencent-Games", "weixin") or from_id.startswith("gh_"):
        msg.skip = True
        return msg
    if any(ind in msg_source for ind in
           ("<tips>3</tips>", "<bizmsgshowtype>", "<bizmsgfromuser>")):
        msg.skip = True
        return msg

    # 消息类型
    if msg.msg_type == 1:
        msg.kind = "text"
        msg.content = msg.raw_content
    elif msg.msg_type == 3:
        msg.kind = "image"
        msg.image_xml = msg.raw_content
    elif msg.msg_type == 34:
        msg.kind = "voice"
    elif msg.msg_type == 47:
        msg.kind = "emoji"
    elif msg.msg_type == 49:
        msg.kind, msg.content, msg.file_info, msg.quote = _parse_appmsg(msg.raw_content)
    elif msg.msg_type == 51:
        msg.skip = True  # 状态同步
        return msg
    elif msg.msg_type == 10002:
        msg.kind = "system"
        msg.skip = True
        return msg
    else:
        msg.kind = "other"

    if msg.is_group:
        # 群消息：content = "sender_wxid:\n正文"
        if ":\n" in msg.raw_content:
            sender, body = msg.raw_content.split(":\n", 1)
            msg.sender_wxid = sender
            msg.content = body
        else:
            msg.sender_wxid = from_id
            msg.content = msg.raw_content
        msg.room_id = from_id

        # @ 检测：优先 MsgSource 的 atuserlist，兜底 PushContent
        mu = _ATUSERLIST_RE.search(msg_source)
        if mu:
            msg.at_me = bot_wxid in mu.group(1)
        else:
            msg.at_me = "在群聊中@了你" in (data.get("PushContent") or "")
    else:
        msg.sender_wxid = from_id
        msg.room_id = from_id

    # 去掉正文中所有 "@昵称 " 前缀
    msg.content = _AT_MENTION_RE.sub("", msg.content).strip()
    return msg


def _parse_appmsg(raw: str):
    """MsgType=49：引用(57) / 文件(6) / 链接分享(5) / 其他"""
    xml_str = raw
    pos = xml_str.find("<?xml")
    if pos != -1:
        xml_str = xml_str[pos:]
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return "text", raw, {}, {}

    appmsg = root.find("appmsg")
    if appmsg is None:
        return "text", raw, {}, {}
    app_type = _xml_find_text(appmsg, "type")
    title = _xml_find_text(appmsg, "title")

    if app_type == "57":  # 引用消息
        quote = {}
        refer = appmsg.find("refermsg")
        if refer is not None:
            quote = {
                "displayname": _xml_find_text(refer, "displayname"),
                "content": _xml_find_text(refer, "content"),
            }
        text = f"「{quote.get('displayname', '')}: {quote.get('content', '')}」\n{title}"
        return "quote", text, {}, quote
    if app_type == "6":  # 文件
        item = appmsg.find("dataitem")
        file_info = {
            "file_name": title or "file",
            "size": int(_xml_find_text(item, "datasize") or 0),
            "aes_key": _xml_find_text(item, "aeskey"),
            "file_id": _xml_find_text(item, "cdnattachurl"),
            "file_key": _xml_find_text(item, "filekey"),
            "suffix": _xml_find_text(item, "fileext") or "bin",
        }
        return "file", title, file_info, {}
    if app_type == "5":  # 链接分享
        return "share", title, {}, {}
    return "text", title or raw, {}, {}
