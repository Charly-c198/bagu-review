"""文本归一化、精确哈希与 SimHash 近似去重。"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿"), None)
_SPACE_RE = re.compile(r"[ \t　]+")
_NEWLINE_RE = re.compile(r"\r\n?")
_WORD_RE = re.compile(r"[a-zA-Z0-9+#.]{2,}")


def normalize_text(value: str | None) -> str:
    """NFKC + 去零宽 + 合并空白；保留代码运算符。"""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_ZERO_WIDTH)
    text = _NEWLINE_RE.sub("\n", text)
    text = _SPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tokens(value: str) -> list[str]:
    text = normalize_text(value)
    compact = re.sub(r"\s+", "", text)
    grams = [compact[i : i + 3] for i in range(max(0, len(compact) - 2))]
    words = _WORD_RE.findall(text.lower())
    return grams + words


def simhash64(value: str) -> str:
    """64 位 SimHash，返回 16 位十六进制字符串。"""
    tokens = _tokens(value)
    if not tokens:
        return "0" * 16
    vector = [0] * 64
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        number = int.from_bytes(digest[:8], "big")
        for bit in range(64):
            vector[bit] += 1 if (number >> bit) & 1 else -1
    result = 0
    for bit in range(64):
        if vector[bit] >= 0:
            result |= 1 << bit
    return f"{result:016x}"


def hamming_hex(left: str | None, right: str | None) -> int:
    if not left or not right:
        return 64
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


def is_near_duplicate(left: str | None, right: str | None, threshold: int = 3) -> bool:
    return hamming_hex(left, right) <= threshold


def question_hash(stem: str) -> str:
    return sha256_text(stem)


def knowledge_hash(title: str, content: str) -> str:
    return sha256_text(f"{title}\n{content}")


def truncate(value: str | None, limit: int = 160) -> str:
    if not value:
        return ""
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"
