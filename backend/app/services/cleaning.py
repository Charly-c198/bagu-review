"""导入/爬虫文本清洗：去广告、水印与纯符号行。

删除的行以空行占位，保持原始行号不变，便于逐行错误定位。
"""

from __future__ import annotations

import re

_AD_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"关注(?:微信)?公众号",
        r"微信搜索",
        r"扫码关注",
        r"加微信",
        r"加QQ群",
        r"点击关注",
        r"点赞.{0,6}收藏",
        r"转载请(?:注明|联系)",
        r"版权归",
        r"如有侵权",
        r"联系删除",
        r"watermark",
        r"广告位",
        r"推广链接",
    )
]
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SYMBOL_ONLY_RE = re.compile(r"^[\W_]{1,6}$", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿A-Za-z0-9]")


def clean_source_text(text: str) -> tuple[str, list[dict]]:
    """返回 (清洗后文本, 清洗记录)。空行占位不改变行号。"""
    removed: list[dict] = []
    output: list[str] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            output.append("")
            continue
        if any(pattern.search(stripped) for pattern in _AD_PATTERNS):
            removed.append({"line": number, "reason": "广告/水印"})
            output.append("")
            continue
        if (
            _SYMBOL_ONLY_RE.match(stripped)
            and not _CJK_RE.search(stripped)
            and stripped not in {"---", "***", "___"}
        ):
            removed.append({"line": number, "reason": "纯符号/表情"})
            output.append("")
            continue
        output.append(line)
    return "\n".join(output), removed
