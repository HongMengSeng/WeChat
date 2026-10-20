"""内置命令系统：#帮助 #模型列表 #模型 #视觉模型 #重置 #状态"""

import logging

log = logging.getLogger("bot.cmd")

HELP_TEXT = (
    "可用命令：\n"
    "#帮助 - 查看本帮助\n"
    "#模型列表 - 查看所有已配置模型\n"
    "#模型 <名称> - 切换本群文本模型，如 #模型 deepseek-reasoner\n"
    "#视觉模型 <名称> - 切换本群视觉模型（识别图片用）\n"
    "#重置 - 清空本群对话上下文和图片记录\n"
    "#状态 - 查看当前模型与统计\n\n"
    "玩法：发图片后 @我 说「这张图是什么」；发 PDF/Word/Excel 后 @我 提问；"
    "说「上一张」「第2张」「XX发的图」可引用群里的历史图片。"
)


def is_command(text: str) -> bool:
    return (text or "").startswith("#") or (text or "").startswith("＃")


def handle(bot, sess, msg, text: str) -> str:
    """执行命令，返回回复文本"""
    arg = text.lstrip("#＃").strip()
    parts = arg.split(None, 1)
    name = parts[0].lower() if parts else ""
    param = parts[1].strip() if len(parts) > 1 else ""

    if name in ("帮助", "help", ""):
        return HELP_TEXT

    if name == "模型列表":
        models = bot.router.list_models()
        return "已配置模型：\n" + "\n".join(models) if models else "未配置任何模型"

    if name == "模型":
        if not param:
            return f"当前文本模型：{sess.model_override or bot.router.default_model}\n用法：#模型 <名称>"
        if not _model_exists(bot, param):
            return f"模型 {param} 不在配置里，用 #模型列表 查看"
        sess.model_override = param
        bot.sessions.save()
        return f"✅ 本群文本模型已切换为 {param}"

    if name == "视觉模型":
        if not param:
            return f"当前视觉模型：{sess.vision_model_override or bot.router.vision_model}\n用法：#视觉模型 <名称>"
        if not _model_exists(bot, param):
            return f"模型 {param} 不在配置里，用 #模型列表 查看"
        sess.vision_model_override = param
        bot.sessions.save()
        return f"✅ 本群视觉模型已切换为 {param}"

    if name in ("重置", "清空", "clear"):
        sess.reset()
        bot.sessions.save()
        return "✅ 已清空本群对话上下文与图片记录"

    if name == "状态":
        st = bot.storage.stats()
        return (
            f"当前模型：{sess.model_override or bot.router.default_model}\n"
            f"视觉模型：{sess.vision_model_override or bot.router.vision_model}\n"
            f"图片栈：{len(sess.images)} 张 / 对话轮数：{len(sess.history) // 2}\n"
            f"累计消息：{st['total']} 条（24h 内 {st['today']} 条）"
        )

    return f"未知命令 #{name}\n" + HELP_TEXT


def _model_exists(bot, model: str) -> bool:
    try:
        bot.router.resolve(model)
        return True
    except (ValueError, KeyError):
        return False
