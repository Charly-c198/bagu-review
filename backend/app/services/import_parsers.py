"""本地导入解析：Markdown / CSV / JSON（含知识条目与组合格式）。"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..utils.text import normalize_text
from .knowledge_extract import extract_from_text


@dataclass
class ParsedQuestion:
    stem: str
    answer: str = ""
    key_points: list[str] = field(default_factory=list)
    category_path: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    difficulty: int | None = None
    frequency: str | None = None
    companies: list[str] = field(default_factory=list)
    notes: str = ""
    line: int = 0
    raw: str = ""
    confidence: float = 0.9


@dataclass
class ParsedKnowledge:
    title: str
    content: str
    kind: str = "concept"
    category_path: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    line: int = 0
    raw: str = ""
    confidence: float = 0.8
    ref: str | None = None


@dataclass
class ParseResult:
    questions: list[ParsedQuestion] = field(default_factory=list)
    knowledge: list[ParsedKnowledge] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    total_rows: int = 0


_QUESTION_HEADING = re.compile(r"^\s{0,3}#{1,4}\s*题目\s*[：:]\s*(.*)$")
_KNOWLEDGE_HEADING = re.compile(r"^\s{0,3}#{1,4}\s*知识\s*[：:]\s*(.*)$")
_FIELD_RE = re.compile(
    r"^\s*(?:\*\*)?(答案|要点|标签|难度|频率|公司|分类|笔记|备注|别名|类型|正文|内容)(?:\*\*)?\s*[：:]\s*(.*)$"
)
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# 仅含 --- / *** / ___ 的主题分隔线：真实面经仓库常用它切段，
# 以前会被并入上一个字段（例如“频率: high\n---”导致整题解析失败）。
_THEMATIC_BREAK_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
# 未知的 **字段**：不并入上一个已知字段，统一收进笔记。
_BOLD_FIELD_RE = re.compile(r"^\s*\*\*([^*\n]{1,30})\*\*\s*(?:[：:]\s*(.*))?$")
_KNOWN_QUESTION_FIELDS = {
    "答案",
    "要点",
    "标签",
    "难度",
    "频率",
    "公司",
    "分类",
    "笔记",
    "备注",
}
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_QUESTION_HINT_RE = re.compile(
    r"(为什么|为何|如何|怎么|怎样|什么|哪些|区别|异同|对比|谈谈|说说|是否|能否|会不会|优缺点|场景)"
)
_INTERVIEW_SECTIONS = {"面试题", "常见面试题", "面试问题", "面试题汇总", "面试题整理"}
_GENERIC_HEADINGS = {
    "目录",
    "前言",
    "序言",
    "总结",
    "小结",
    "参考",
    "参考资料",
    "参考链接",
    "相关阅读",
    "扩展阅读",
    "面试官心理分析",
    "面试题剖析",
    "面试题分析",
    "更新记录",
    "致谢",
    "版权声明",
    "license",
    "鸣谢",
    "题目描述",
    "题目",
    "解答思路",
    "解题思路",
    "思路",
    "方法总结",
    "解法",
    "答案",
    "代码",
    "代码实现",
    "实现",
    "分析",
    "扩展",
    "脚注",
    "公众号",
    "微信",
    "广告",
}
# 形如“方法一：分治法”“第二种方案”的小节标题脱离上下文后没有知识价值。
_GENERIC_TITLE_RE = re.compile(r"^(?:方法|方案|解法|第)[一二三四五六七八九十0-9]+")
_MAX_FREE_QUESTIONS = 120
_MAX_FREE_KNOWLEDGE = 60


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请使用 UTF-8 或 GB18030")


def _split_list(value: Any, separators: str = r"[,，、;；\n]+") -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(separators, str(value)) if part.strip()]


def _split_key_points(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value is None:
        return []
    return [
        part.strip()
        for part in re.split(r"[;；、\n]+", str(value))
        if part.strip()
    ]


def _category_path(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
    else:
        parts = [p.strip() for p in str(value).split("/") if p.strip()]
    return parts[:3]


def _parse_difficulty(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    number = int(str(value).strip())
    if not 1 <= number <= 5:
        raise ValueError("难度必须在 1-5 之间")
    return number


def _parse_frequency(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    mapping = {
        "high": "high",
        "高": "high",
        "高频": "high",
        "mid": "mid",
        "medium": "mid",
        "中": "mid",
        "中频": "mid",
        "low": "low",
        "低": "low",
        "低频": "low",
    }
    if text not in mapping:
        raise ValueError("频率必须是 high / mid / low")
    return mapping[text]


def _kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "concept": "concept",
        "概念": "concept",
        "principle": "principle",
        "原理": "principle",
        "process": "process",
        "流程": "process",
        "comparison": "comparison",
        "对比": "comparison",
        "区别": "comparison",
        "pitfall": "pitfall",
        "易错点": "pitfall",
        "注意": "pitfall",
        "other": "other",
    }
    return mapping.get(text, "other")


def _clean_heading(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^\d+(?:\.\d+)*[.、)]\s*", "", text)
    text = re.sub(r"^[Qq]\d*[.、:：]\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("`", "").strip(" #*")
    return text.strip()


def _looks_like_question(title: str) -> bool:
    if not title:
        return False
    if title.endswith(("？", "?")):
        return True
    return bool(_QUESTION_HINT_RE.search(title))


def _question_split(body: str) -> list[str]:
    """把“面试题”段落拆成单个问题；只保留像问题的句子。"""
    questions: list[str] = []
    for chunk in re.split(r"(?<=[？?])|\n+", body):
        text = chunk.strip().lstrip("-*0123456789.、 ").strip()
        if not 6 <= len(text) <= 120:
            continue
        if text.endswith(("？", "?")) or _QUESTION_HINT_RE.search(text):
            questions.append(text)
    return questions


def _iter_sections(text: str):
    """按标题切段；代码块内标题不切分。返回 (级别, 标题, 行号, 正文, 原文)。"""
    sections: list[tuple[int, str, int, str, str]] = []
    in_fence = False
    current: list[str] | None = None
    meta: tuple[int, str, int] | None = None

    def flush() -> None:
        if current is not None and meta is not None:
            raw = "\n".join(current).strip()
            body = "\n".join(current[1:]).strip()
            sections.append((meta[0], meta[1], meta[2], body, raw))

    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            if current is not None:
                current.append(line)
            continue
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            flush()
            meta = (len(match.group(1)), match.group(2).strip(), number)
            current = [line]
            continue
        if current is not None:
            current.append(line)
        elif line.strip():
            current = [line]
            meta = (0, "", number)
    flush()
    return sections


def _kind_from_title(title: str) -> str:
    for label, kind in (
        ("区别", "comparison"),
        ("对比", "comparison"),
        ("比较", "comparison"),
        ("原理", "principle"),
        ("流程", "process"),
        ("步骤", "process"),
        ("注意", "pitfall"),
        ("坑", "pitfall"),
        ("最佳实践", "pitfall"),
    ):
        if label in title:
            return kind
    return "concept"


def parse_free_markdown(text: str) -> ParseResult:
    """无 `## 题目：` 标记的自由 Markdown（真实面经仓库的常见形态）。

    标题像问题的按题切分，正文作答案；其余标题按知识条目收集。
    “面试题”小节逐句拆题。全部低置信度，待审区会置顶提示人工修正。
    """
    result = ParseResult()
    seen: set[str] = set()
    knowledge_seen: set[str] = set()
    sections = _iter_sections(text)
    if sections and sections[0][0] == 0:
        _, _, _, preamble, _ = sections[0]
        if preamble.strip():
            for item in extract_from_text(preamble, confidence=0.4):
                result.total_rows += 1
                result.knowledge.append(
                    ParsedKnowledge(
                        title=item.title,
                        content=item.content,
                        kind=item.kind,
                        line=0,
                        raw=item.raw,
                        confidence=0.4,
                    )
                )

    for level, raw_title, line, body, raw in sections:
        title = _clean_heading(raw_title)
        if not title:
            continue
        if title.lower() in _GENERIC_HEADINGS:
            continue

        if title in _INTERVIEW_SECTIONS or title.endswith("面试题"):
            for question in _question_split(body):
                key = normalize_text(question)
                if key in seen or len(result.questions) >= _MAX_FREE_QUESTIONS:
                    continue
                seen.add(key)
                result.total_rows += 1
                result.questions.append(
                    ParsedQuestion(
                        stem=key,
                        answer="",
                        line=line,
                        raw=raw,
                        confidence=0.4,
                    )
                )
            continue

        if _looks_like_question(title) and level >= 1:
            answer = re.sub(r"^(?:答|答案)\s*[：:]\s*", "", body).strip()
            key = normalize_text(title)
            if key in seen or len(result.questions) >= _MAX_FREE_QUESTIONS:
                continue
            if not answer and level > 1:
                # 无正文的空标题多半是目录项，不作为题目。
                continue
            seen.add(key)
            result.total_rows += 1
            result.questions.append(
                ParsedQuestion(
                    stem=key,
                    answer=normalize_text(answer),
                    line=line,
                    raw=raw,
                    confidence=0.5 if answer else 0.35,
                )
            )
            continue

        # 其余标题作为知识候选：过滤目录式（只有链接列表）和过短正文。
        body_lines = [line_ for line_ in body.splitlines() if line_.strip()]
        if not body_lines:
            continue
        if all(line_.lstrip().startswith(("-", "*", "|", ">", "!")) for line_ in body_lines):
            continue
        content = normalize_text(body)
        if len(content) < 30 or len(title) > 80:
            continue
        if len(title) < 4 or _GENERIC_TITLE_RE.match(title) or "公众号" in title:
            continue
        key = normalize_text(title)
        if key in knowledge_seen or len(result.knowledge) >= _MAX_FREE_KNOWLEDGE:
            continue
        knowledge_seen.add(key)
        result.total_rows += 1
        result.knowledge.append(
            ParsedKnowledge(
                title=title,
                content=content[:2000],
                kind=_kind_from_title(title),
                line=line,
                raw=raw,
                confidence=0.4,
            )
        )
    return result


def parse_markdown(text: str) -> ParseResult:
    lines = text.splitlines()
    explicit = False
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and (_QUESTION_HEADING.match(line) or _KNOWLEDGE_HEADING.match(line)):
            explicit = True
            break
    if not explicit:
        # 没有约定问答标记：按标题/问答启发式切分（文档 4.3.3、附录 A.1）。
        return parse_free_markdown(text)

    result = ParseResult()
    in_fence = False
    preamble: list[str] = []

    current_type: str | None = None  # question / knowledge
    current_heading = ""
    current_line = 0
    current_lines: list[str] = []
    fields: dict[str, list[str]] = {}
    stem_lines: list[str] = []
    content_lines: list[str] = []
    current_field: str | None = None

    def reset() -> None:
        nonlocal current_type, current_heading, current_line, current_lines
        nonlocal fields, stem_lines, content_lines, current_field
        current_type = None
        current_heading = ""
        current_line = 0
        current_lines = []
        fields = {}
        stem_lines = []
        content_lines = []
        current_field = None

    def finish() -> None:
        nonlocal current_type
        if current_type is None:
            return
        raw = "\n".join(current_lines).strip()
        if current_type == "question":
            heading = normalize_text(current_heading)
            stem = "\n".join(stem_lines).strip()
            if heading and stem:
                stem = f"{heading}\n{stem}"
            elif heading:
                stem = heading
            if not stem:
                result.errors.append(
                    {"line": current_line, "message": "题目缺少题干", "type": "question"}
                )
                result.total_rows += 1
                return
            try:
                difficulty = _parse_difficulty(
                    "\n".join(fields.get("难度", [])).strip()
                )
                frequency = _parse_frequency(
                    "\n".join(fields.get("频率", [])).strip()
                )
            except (TypeError, ValueError) as exc:
                result.errors.append(
                    {"line": current_line, "message": str(exc), "type": "question"}
                )
                result.total_rows += 1
                return
            answer = "\n".join(fields.get("答案", [])).strip()
            notes = list(fields.get("笔记", []) + fields.get("备注", []))
            for name, values in fields.items():
                if name not in _KNOWN_QUESTION_FIELDS and values:
                    notes.append(name + "：" + "\n".join(values).strip())
            result.questions.append(
                ParsedQuestion(
                    stem=normalize_text(stem),
                    answer=answer,
                    key_points=_split_key_points("\n".join(fields.get("要点", []))),
                    category_path=_category_path(
                        "\n".join(fields.get("分类", [])).strip()
                    ),
                    tags=_split_list("\n".join(fields.get("标签", []))),
                    difficulty=difficulty,
                    frequency=frequency,
                    companies=_split_list("\n".join(fields.get("公司", []))),
                    notes="\n".join(notes).strip(),
                    line=current_line,
                    raw=raw,
                    confidence=0.9 if answer else 0.7,
                )
            )
            result.total_rows += 1
        elif current_type == "knowledge":
            title = normalize_text(current_heading)
            content = "\n".join(content_lines).strip()
            if not title or not content:
                result.errors.append(
                    {"line": current_line, "message": "知识条目缺少标题或内容", "type": "knowledge"}
                )
                result.total_rows += 1
                return
            result.knowledge.append(
                ParsedKnowledge(
                    title=title,
                    content=normalize_text(content),
                    kind=_kind("\n".join(fields.get("类型", [])).strip()),
                    category_path=_category_path(
                        "\n".join(fields.get("分类", [])).strip()
                    ),
                    aliases=_split_list("\n".join(fields.get("别名", []))),
                    line=current_line,
                    raw=raw,
                    confidence=0.85,
                )
            )
            result.total_rows += 1
        reset()

    for number, line in enumerate(lines, start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            if current_type == "question":
                if current_field is None:
                    stem_lines.append(line)
                else:
                    fields.setdefault(current_field, []).append(line)
            elif current_type == "knowledge":
                content_lines.append(line)
            else:
                preamble.append(line)
            continue

        if not in_fence:
            if current_type is not None and _THEMATIC_BREAK_RE.match(line):
                finish()
                continue
            question_match = _QUESTION_HEADING.match(line)
            knowledge_match = _KNOWLEDGE_HEADING.match(line)
            if question_match or knowledge_match:
                finish()
                current_type = "question" if question_match else "knowledge"
                current_heading = (question_match or knowledge_match).group(1).strip()
                current_line = number
                current_lines = [line]
                continue

        if current_type is None:
            preamble.append(line)
            continue

        current_lines.append(line)
        if in_fence:
            if current_type == "question" and current_field is None:
                stem_lines.append(line)
            else:
                content_lines.append(line)
            continue

        match = _FIELD_RE.match(line)
        if match:
            field_name, value = match.group(1), match.group(2)
            current_field = field_name
            fields.setdefault(field_name, []).append(value)
            if current_type == "knowledge" and field_name in ("内容", "正文"):
                content_lines.append(value)
            continue

        if current_type == "question":
            bold = _BOLD_FIELD_RE.match(line)
            if bold:
                # 面经里常见 **面试官**：... 之类的附加字段；不能并入上一个字段，
                # 否则会把“频率”污染成 "high\n**面试官**…" 导致整题报错。
                current_field = bold.group(1).strip()
                fields.setdefault(current_field, []).append((bold.group(2) or "").strip())
                continue
            if current_field is None:
                stem_lines.append(line)
            else:
                fields.setdefault(current_field, []).append(line)
        else:
            if current_field in (None, "内容", "正文"):
                content_lines.append(line)

    finish()

    preamble_text = "\n".join(preamble).strip()
    if preamble_text:
        for item in extract_from_text(preamble_text, confidence=0.45):
            result.total_rows += 1
            result.knowledge.append(
                ParsedKnowledge(
                    title=item.title,
                    content=item.content,
                    kind=item.kind,
                    line=0,
                    raw=item.raw,
                    confidence=item.confidence,
                )
            )
    return result


_CSV_ALIASES = {
    "stem": "stem",
    "题干": "stem",
    "question": "stem",
    "answer": "answer",
    "答案": "answer",
    "key_points": "key_points",
    "要点": "key_points",
    "category_path": "category_path",
    "category": "category_path",
    "分类": "category_path",
    "tags": "tags",
    "标签": "tags",
    "difficulty": "difficulty",
    "难度": "difficulty",
    "frequency": "frequency",
    "频率": "frequency",
    "companies": "companies",
    "company": "companies",
    "公司": "companies",
    "notes": "notes",
    "笔记": "notes",
}


def parse_csv(text: str) -> ParseResult:
    result = ParseResult()
    stream = io.StringIO(text)
    reader = csv.reader(stream)
    try:
        header = next(reader)
    except StopIteration:
        result.errors.append({"record": 0, "line": 0, "message": "CSV 文件为空"})
        return result
    normalized = [_CSV_ALIASES.get(h.strip().lower(), _CSV_ALIASES.get(h.strip(), h.strip().lower())) for h in header]
    if "stem" not in normalized:
        result.errors.append(
            {
                "record": 0,
                "line": reader.line_num,
                "message": "CSV 缺少必填列 stem（题干）",
            }
        )
        return result

    record = 0
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        record += 1
        result.total_rows += 1
        line_no = reader.line_num
        values: dict[str, str] = {}
        for index, key in enumerate(normalized):
            if index < len(row):
                values[key] = row[index]
        stem = values.get("stem", "").strip()
        if not stem:
            result.errors.append(
                {"record": record, "line": line_no, "message": "题干不能为空"}
            )
            continue
        try:
            difficulty = _parse_difficulty(values.get("difficulty"))
            frequency = _parse_frequency(values.get("frequency"))
        except (TypeError, ValueError) as exc:
            result.errors.append(
                {"record": record, "line": line_no, "message": str(exc)}
            )
            continue
        result.questions.append(
            ParsedQuestion(
                stem=normalize_text(stem),
                answer=values.get("answer", "").strip(),
                key_points=_split_key_points(values.get("key_points")),
                category_path=_category_path(values.get("category_path")),
                tags=_split_list(values.get("tags")),
                difficulty=difficulty,
                frequency=frequency,
                companies=_split_list(values.get("companies")),
                notes=values.get("notes", "").strip(),
                line=line_no,
                raw=",".join(row),
                confidence=0.95,
            )
        )
    return result


def _json_question(item: dict, index: int) -> ParsedQuestion:
    stem = normalize_text(str(item.get("stem", "")))
    if not stem:
        raise ValueError("stem 不能为空")
    return ParsedQuestion(
        stem=stem,
        answer=str(item.get("answer", "") or "").strip(),
        key_points=_split_key_points(item.get("key_points")),
        category_path=_category_path(item.get("category_path")),
        tags=_split_list(item.get("tags")),
        difficulty=_parse_difficulty(item.get("difficulty")),
        frequency=_parse_frequency(item.get("frequency")),
        companies=_split_list(item.get("companies")),
        notes=str(item.get("notes", "") or "").strip(),
        line=index,
        raw=json.dumps(item, ensure_ascii=False),
        confidence=0.95,
    )


def _json_knowledge(item: dict, index: int) -> ParsedKnowledge:
    title = normalize_text(str(item.get("title", "")))
    content = normalize_text(str(item.get("content", "")))
    if not title or not content:
        raise ValueError("知识条目标题和内容不能为空")
    return ParsedKnowledge(
        title=title,
        content=content,
        kind=_kind(item.get("kind")),
        category_path=_category_path(item.get("category_path")),
        aliases=_split_list(item.get("aliases")),
        line=index,
        raw=json.dumps(item, ensure_ascii=False),
        confidence=0.95,
        ref=str(item.get("ref")) if item.get("ref") is not None else None,
    )


def parse_json(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：第 {exc.lineno} 行 {exc.msg}") from exc

    result = ParseResult()
    if isinstance(data, list):
        for index, item in enumerate(data):
            result.total_rows += 1
            if not isinstance(item, dict):
                result.errors.append(
                    {"index": index, "message": "数组元素必须是对象"}
                )
                continue
            try:
                if "stem" in item:
                    result.questions.append(_json_question(item, index))
                elif "title" in item and "content" in item:
                    result.knowledge.append(_json_knowledge(item, index))
                else:
                    raise ValueError("对象需包含 stem，或包含 title + content")
            except (TypeError, ValueError) as exc:
                result.errors.append({"index": index, "message": str(exc)})
        return result

    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是数组或包含 questions/knowledge 的对象")

    questions = data.get("questions") or []
    knowledge = data.get("knowledge") or []
    if not isinstance(questions, list) or not isinstance(knowledge, list):
        raise ValueError("questions 与 knowledge 必须是数组")

    for index, item in enumerate(questions):
        result.total_rows += 1
        if not isinstance(item, dict):
            result.errors.append({"index": index, "field": "questions", "message": "必须是对象"})
            continue
        try:
            result.questions.append(_json_question(item, index))
        except (TypeError, ValueError) as exc:
            result.errors.append({"index": index, "field": "questions", "message": str(exc)})

    for index, item in enumerate(knowledge):
        result.total_rows += 1
        if not isinstance(item, dict):
            result.errors.append({"index": index, "field": "knowledge", "message": "必须是对象"})
            continue
        try:
            result.knowledge.append(_json_knowledge(item, index))
        except (TypeError, ValueError) as exc:
            result.errors.append({"index": index, "field": "knowledge", "message": str(exc)})

    refs = {item.ref for item in result.knowledge if item.ref}
    raw_links = data.get("links") or []
    if not isinstance(raw_links, list):
        result.errors.append({"index": 0, "field": "links", "message": "links 必须是数组"})
    else:
        for index, link in enumerate(raw_links):
            if not isinstance(link, dict):
                result.errors.append({"index": index, "field": "links", "message": "必须是对象"})
                continue
            q_index = link.get("question_index")
            k_ref = link.get("knowledge_ref")
            if not isinstance(q_index, int) or not 0 <= q_index < len(result.questions):
                result.errors.append(
                    {"index": index, "field": "links", "message": "question_index 引用无效"}
                )
                continue
            if k_ref not in refs:
                result.errors.append(
                    {"index": index, "field": "links", "message": "knowledge_ref 引用无效"}
                )
                continue
            relation = str(link.get("relation_type", "related"))
            if relation not in ("related", "prerequisite", "derived_from"):
                relation = "related"
            result.links.append(
                {"question_index": q_index, "knowledge_ref": k_ref, "relation_type": relation}
            )
    return result


def parse_content(fmt: str, text: str) -> ParseResult:
    fmt = fmt.lower()
    if fmt in ("md", "markdown", "paste"):
        return parse_markdown(text)
    if fmt == "csv":
        return parse_csv(text)
    if fmt == "json":
        return parse_json(text)
    raise ValueError(f"不支持的导入格式：{fmt}")
