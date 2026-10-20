"""文档文本提取：PDF / Word / Excel / CSV / TXT"""

import logging
from pathlib import Path

log = logging.getLogger("bot.files")

MAX_CHARS = 6000  # 提取文本上限，防止 token 爆炸


def extract_text(path: str) -> str:
    """按扩展名提取文本，失败返回空串"""
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(p)
        if ext == ".docx":
            return _docx(p)
        if ext in (".xlsx", ".xlsm"):
            return _xlsx(p)
        if ext in (".txt", ".md", ".csv", ".json", ".log", ".py", ".html", ".xml"):
            return _plain(p)
        if ext == ".doc":
            return "（暂不支持旧版 .doc，请转存为 .docx 或 PDF）"
        return ""
    except Exception as e:
        log.warning("文件解析失败 %s: %s", p.name, e)
        return ""


def _clip(text: str) -> str:
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n…（内容过长，已截断，全文共 {len(text)} 字符）"
    return text


def _pdf(p: Path) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(str(p)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            parts.append(t)
            if sum(len(x) for x in parts) > MAX_CHARS * 2:
                break
    return _clip("\n".join(parts))


def _docx(p: Path) -> str:
    import docx
    d = docx.Document(str(p))
    parts = [para.text for para in d.paragraphs if para.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            parts.append(" | ".join(cells))
    return _clip("\n".join(parts))


def _xlsx(p: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"=== 工作表: {ws.title} ===")
        for row in ws.iter_rows(max_row=200, values_only=True):
            if any(v is not None for v in row):
                parts.append(" | ".join("" if v is None else str(v) for v in row))
            if len(parts) > 400:
                break
    wb.close()
    return _clip("\n".join(parts))


def _plain(p: Path) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return _clip(p.read_text(encoding=enc))
        except UnicodeDecodeError:
            continue
    return ""
