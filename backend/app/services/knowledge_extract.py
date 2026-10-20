"""知识条目规则抽取：显式“知识”块 + 定义/原理/对比等段落启发式。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..utils.text import normalize_text, truncate


@dataclass
class ExtractedKnowledge:
    title: str
    content: str
    kind: str = "concept"
    confidence: float = 0.5
    raw: str = ""
    aliases: list[str] = field(default_factory=list)


_LABEL_KIND = {
    "定义": "concept",
    "概念": "concept",
    "原理": "principle",
    "为什么": "principle",
    "流程": "process",
    "步骤": "process",
    "区别": "comparison",
    "对比": "comparison",
    "比较": "comparison",
    "注意": "pitfall",
    "易错": "pitfall",
    "易错点": "pitfall",
    "坑": "pitfall",
}

_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(定义|概念|原理|为什么|流程|步骤|区别|对比|比较|注意|易错点|易错|坑)(?:\*\*)?\s*[：:]\s*(.+)$"
)
_BOLD_RE = re.compile(r"^\s*\*\*([^*]{2,40})\*\*\s*[：:]?\s*(.*)$")


def _make(title: str, content: str, kind: str, confidence: float, raw: str) -> ExtractedKnowledge | None:
    content = normalize_text(content)
    title = normalize_text(title)
    if len(content) < 12 or len(title) < 2:
        return None
    return ExtractedKnowledge(
        title=truncate(title, 80),
        content=content,
        kind=kind,
        confidence=confidence,
        raw=raw,
    )


def extract_from_text(
    text: str,
    base_title: str | None = None,
    *,
    confidence: float = 0.5,
) -> list[ExtractedKnowledge]:
    """从自由文本抽取候选知识条目；宁缺毋滥，低置信度交由人工审核。"""
    text = normalize_text(text)
    if not text:
        return []
    results: list[ExtractedKnowledge] = []
    seen: set[str] = set()

    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0]
        match = _LABEL_RE.match(first)
        if match:
            label, rest = match.group(1), match.group(2)
            body = "\n".join([rest] + lines[1:])
            if base_title:
                title = f"{truncate(base_title, 26)} · {label}"
            else:
                title = f"{label}：{truncate(rest, 24)}"
            item = _make(
                title,
                body,
                _LABEL_KIND.get(label, "concept"),
                confidence,
                block,
            )
            if item:
                key = item.title + item.content
                if key not in seen:
                    seen.add(key)
                    results.append(item)
            continue

        bold = _BOLD_RE.match(first)
        if bold and len(lines) >= 2:
            title, rest = bold.group(1), bold.group(2)
            if title in {"答案", "要点", "标签", "难度", "频率", "公司", "分类", "笔记"}:
                continue
            body = "\n".join([rest] + lines[1:]) if rest else "\n".join(lines[1:])
            item = _make(
                f"{truncate(base_title, 26)} · {title}" if base_title else title,
                body,
                "concept",
                max(0.4, confidence - 0.05),
                block,
            )
            if item:
                key = item.title + item.content
                if key not in seen:
                    seen.add(key)
                    results.append(item)

    return results[:20]


def build_keypoints_candidate(
    stem: str, key_points: list[str], answer: str | None = None
) -> ExtractedKnowledge | None:
    """题目审核通过时，从结构化要点生成一条待审知识候选。"""
    points = [p.strip() for p in key_points if p and p.strip()]
    if len(points) < 3:
        return None
    title = f"{truncate(stem, 30)} · 要点"
    content = "；".join(points)
    if answer and len(content) < 20:
        content = f"{content}。{truncate(answer, 80)}"
    return _make(title, content, "concept", 0.4, content)
