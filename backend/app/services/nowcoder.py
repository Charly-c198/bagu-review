"""牛客公开页爬虫（M2）。

仅采集公开页面：讨论区帖子（`/discuss/<id>`）与站点 sitemap。牛客对爬虫 UA
返回服务端渲染的完整 HTML（浏览器 UA 反而拿到 SPA 壳），因此用 httpx 即可解析，
不需要 Playwright。遵守 robots.txt，默认请求间隔来自源配置。
"""

from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from ..config import GITHUB_SSL_MODE
from ..errors import ApiError
from ..utils.text import normalize_text
from .import_parsers import ParsedQuestion, parse_markdown

ALLOWED_HOSTS = {"nowcoder.com", "www.nowcoder.com"}
DISCUSS_HOST = "https://www.nowcoder.com"
ROBOTS_TTL = 3600.0
MAX_HTML_BYTES = 4 * 1024 * 1024
_TITLE_RE = re.compile(
    r'<div[^>]*class="[^"]*content-post-title[^"]*"[^>]*>.*?<h1[^>]*>(.*?)</h1>',
    re.S | re.I,
)
_CONTENT_START_RE = re.compile(
    r'<div[^>]*class="[^"]*nc-slate-editor-content[^"]*"[^>]*>', re.I
)
_RICH_TEXT_RE = re.compile(r'"richText":"((?:[^"\\]|\\.)*)"')
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_POST_PATH_RE = re.compile(r"^/discuss/(\d+)")
_NUMBERED_Q_RE = re.compile(r"^\s*(?:\*\*)?\s*(\d{1,3})[.、]\s*(?:\*\*)?\s*(.+)$")
_ANSWER_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:答案|参考答案)\s*[：:]\s*(.+?)(?:\*\*)?\s*$"
)


@dataclass
class NowcoderTarget:
    kind: str  # post / sitemap
    url: str


def parse_nowcoder_source(url: str) -> NowcoderTarget:
    if not url or not url.strip():
        raise ApiError(400, "VALIDATION_ERROR", "源 URL 不能为空")
    split = urlsplit(url.strip())
    if split.scheme != "https":
        raise ApiError(400, "VALIDATION_ERROR", "仅支持 https URL")
    if (split.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ApiError(400, "VALIDATION_ERROR", "牛客源仅支持 nowcoder.com 域名")
    path = split.path or "/"
    if _POST_PATH_RE.match(path):
        return NowcoderTarget(kind="post", url=url.strip())
    if path.lower().endswith(".xml"):
        return NowcoderTarget(kind="sitemap", url=url.strip())
    if path.startswith("/discuss"):
        # 列表页是 SPA，服务端不输出帖子链接；引导用帖子 URL 或 sitemap。
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "牛客列表页为动态渲染，请配置具体帖子 URL 或站点 sitemap URL",
        )
    raise ApiError(
        400,
        "VALIDATION_ERROR",
        "牛客源支持 /discuss/<id> 帖子 URL 或 /sitemap*.xml",
    )


def validate_nowcoder_source(url: str) -> None:
    parse_nowcoder_source(url)


def _resolve_verify(mode: str | None) -> bool | ssl.SSLContext:
    mode = (mode or "certifi").strip().lower()
    if mode in ("system", "os", "native"):
        return ssl.create_default_context()
    if mode in ("none", "off", "insecure"):
        return False
    return True


class _MarkdownHTMLParser(HTMLParser):
    """把牛客正文 HTML 转成保留标题/列表/代码块的 Markdown 文本。"""

    BLOCK_TAGS = {"p", "div", "section", "article", "tr", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.in_pre = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag in ("script", "style", "head", "noscript"):
            self.skip += 1
            return
        if self.skip:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "pre":
            self.parts.append("\n\n```\n")
            self.in_pre = True
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "head", "noscript"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "pre":
            self.parts.append("\n```\n")
            self.in_pre = False
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.in_pre:
            self.parts.append(data)
        else:
            text = re.sub(r"[ \t　]+", " ", data)
            if text.strip():
                self.parts.append(text)

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _extract_content_html(page: str) -> str:
    match = _CONTENT_START_RE.search(page)
    if match:
        rest = page[match.end() :]
        inner = re.match(r"\s*(<html[\s\S]*?</html>)", rest, re.I)
        if inner:
            return inner.group(1)
        end = rest.find("</div>")
        return rest[: end if end >= 0 else 200_000]
    rich = _RICH_TEXT_RE.search(page)
    if rich:
        try:
            return json.loads('"' + rich.group(1) + '"')
        except json.JSONDecodeError:
            pass
    return ""


def extract_post(page: str) -> tuple[str, str]:
    """返回 (标题, Markdown 正文)；无法提取时返回空正文。"""
    title_match = _TITLE_RE.search(page)
    title = unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""
    content_html = _extract_content_html(page)
    if not content_html:
        return title, ""
    parser = _MarkdownHTMLParser()
    parser.feed(content_html)
    body = parser.markdown()
    return title, body


def extract_numbered_questions(markdown: str) -> list[ParsedQuestion]:
    """从笔试/面经正文里提取“1. 题目 … 答案：…”形式的问答。"""
    lines = markdown.splitlines()
    questions: list[ParsedQuestion] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = _NUMBERED_Q_RE.match(line)
        if not match:
            continue
        stem = match.group(2).strip().strip("*").strip()
        if len(stem) < 10:
            continue
        looks_question = (
            "（）" in stem
            or "()" in stem
            or stem.endswith(("？", "?"))
            or any(word in stem for word in ("什么", "如何", "为什么", "区别", "哪些", "是否"))
        )
        if not looks_question:
            continue
        answer = ""
        for follower in lines[index + 1 : index + 40]:
            answer_match = _ANSWER_RE.match(follower)
            if answer_match:
                answer = answer_match.group(1).strip().strip("*").strip()
                break
            if _NUMBERED_Q_RE.match(follower):
                break
        key = normalize_text(stem)
        if key in seen:
            continue
        seen.add(key)
        questions.append(
            ParsedQuestion(
                stem=key,
                answer=answer,
                line=index + 1,
                raw="\n".join([line, answer]) if answer else line,
                confidence=0.6 if answer else 0.4,
            )
        )
    return questions


def parse_nowcoder_post(markdown: str):
    """结构化解析牛客帖子：标题/小节走通用规则，编号问答单独抽取。"""
    result = parse_markdown(markdown)
    existing = {item.stem for item in result.questions}
    for question in extract_numbered_questions(markdown):
        if question.stem not in existing:
            result.questions.append(question)
            existing.add(question.stem)
            result.total_rows += 1
    return result


class NowcoderClient:
    def __init__(
        self,
        *,
        timeout: int = 15,
        user_agent: str = "InterviewReviewBot/1.0 (+personal use)",
        spacing_sec: int = 0,
        ssl_mode: str | None = None,
    ) -> None:
        self.spacing_sec = spacing_sec
        self.verify = _resolve_verify(ssl_mode or GITHUB_SSL_MODE)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=self.verify,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            },
        )
        self._robots: tuple[float, list[str]] | None = None

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "NowcoderClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _disallow_rules(self) -> list[str]:
        now = time.monotonic()
        if self._robots and now - self._robots[0] < ROBOTS_TTL:
            return self._robots[1]
        rules: list[str] = []
        try:
            response = self.client.get(f"{DISCUSS_HOST}/robots.txt")
            if response.status_code == 200:
                active = False
                for line in response.text.splitlines():
                    text = line.split("#", 1)[0].strip()
                    if not text or ":" not in text:
                        continue
                    key, value = text.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key == "user-agent":
                        active = value == "*" or "interviewreviewbot" in value.lower()
                    elif key == "disallow" and active and value:
                        rules.append(value)
        except httpx.HTTPError:
            rules = []
        self._robots = (now, rules)
        return rules

    def check_robots(self, target: NowcoderTarget) -> None:
        path = urlsplit(target.url).path or "/"
        for rule in self._disallow_rules():
            prefix = rule.rstrip("*")
            if path.startswith(prefix):
                raise ApiError(
                    400,
                    "CRAWL_DISALLOWED",
                    f"robots.txt 禁止采集该路径：{rule}",
                )

    def _fetch_page(self, url: str) -> httpx.Response:
        response = self.client.get(url)
        if len(response.content) > MAX_HTML_BYTES:
            raise ValueError("页面超过 4MB 限制")
        return response

    def list_files(self, target: NowcoderTarget, max_files: int) -> list[str]:
        if target.kind == "post":
            return [target.url]
        response = self._fetch_page(target.url)
        if response.status_code != 200:
            raise ApiError(
                400, "CRAWL_FAILED", f"无法读取 sitemap：HTTP {response.status_code}"
            )
        urls = self._collect_discuss_urls(response.text, max_files)
        if not urls:
            # sitemap 索引：再取一层子 sitemap。
            children = [
                loc for loc in _LOC_RE.findall(response.text) if loc.endswith(".xml")
            ][:5]
            for child in children:
                child_response = self._fetch_page(child)
                if child_response.status_code != 200:
                    continue
                urls.extend(self._collect_discuss_urls(child_response.text, max_files - len(urls)))
                if len(urls) >= max_files:
                    break
        return urls[:max_files]

    @staticmethod
    def _collect_discuss_urls(xml_text: str, limit: int) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for loc in _LOC_RE.findall(xml_text):
            split = urlsplit(loc)
            match = _POST_PATH_RE.match(split.path or "")
            if not match:
                continue
            url = f"{DISCUSS_HOST}/discuss/{match.group(1)}"
            if url not in seen:
                seen.add(url)
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def fetch_post(self, url: str) -> tuple[int, str, str]:
        response = self._fetch_page(url)
        if response.status_code != 200:
            return response.status_code, "", ""
        title, body = extract_post(response.text)
        if not body:
            raise ValueError("页面未包含可解析的公开正文")
        heading = f"# {title}\n\n" if title else ""
        return 200, title, heading + body
