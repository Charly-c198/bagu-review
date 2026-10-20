"""GitHub Markdown 爬虫：源校验、tree 列表、raw 下载、逐文件解析入库。

M1 仅支持公开 GitHub 仓库的 Markdown 文件；牛客爬虫按文档放到 M2。
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select

from ..config import DATA_DIR, GITHUB_SSL_MODE
from ..database import session_scope
from ..errors import ApiError
from ..models import CrawlSource, CrawlTask, CrawlTaskFile
from ..utils.timeutil import utcnow
from .cleaning import clean_source_text
from .import_parsers import parse_markdown
from .ingest import ingest_parse_result

ALLOWED_HOSTS = {
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
    "api.github.com",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
MIN_INTERVAL = 1
FETCH_SOCKET_RETRIES = 3
KEEPALIVE_EXPIRY = 15.0
# 单个文件的总处理时限 = 系数 × timeout_sec（覆盖各次重试），防止一个文件拖住整批。
FILE_DEADLINE_FACTOR = 5
USER_AGENT_PREFIX = "InterviewReviewBot"


def _remaining_timeout(timeout_sec: int, deadline: float) -> float:
    remaining = deadline - time.monotonic()
    return max(1.0, min(float(timeout_sec), remaining))


@dataclass
class GitHubTarget:
    owner: str
    repo: str
    ref: str | None = None
    path: str = ""


def parse_github_source(url: str) -> GitHubTarget:
    if not url or not url.strip():
        raise ApiError(400, "VALIDATION_ERROR", "源 URL 不能为空")
    split = urlsplit(url.strip())
    if split.scheme != "https":
        raise ApiError(400, "VALIDATION_ERROR", "仅支持 https URL")
    host = (split.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ApiError(
            400, "VALIDATION_ERROR", "M1 仅支持 github.com / raw.githubusercontent.com"
        )
    parts = [part for part in split.path.split("/") if part]
    if host == "raw.githubusercontent.com":
        if len(parts) < 4:
            raise ApiError(400, "VALIDATION_ERROR", "raw URL 格式应为 /owner/repo/ref/path")
        return GitHubTarget(
            owner=parts[0], repo=parts[1], ref=parts[2], path="/".join(parts[3:])
        )
    if len(parts) < 2:
        raise ApiError(400, "VALIDATION_ERROR", "GitHub URL 需包含 owner/repo")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    rest = parts[2:]
    ref = None
    path = ""
    if rest:
        if rest[0] in ("tree", "blob") and len(rest) >= 2:
            ref = rest[1]
            path = "/".join(rest[2:])
        else:
            path = "/".join(rest)
    return GitHubTarget(owner=owner, repo=repo, ref=ref, path=path)


def validate_source_url(url: str) -> None:
    parse_github_source(url)


def resolve_ssl_verify(mode: str | None) -> bool | ssl.SSLContext:
    """把配置值转成 httpx 的 verify 参数。"""
    mode = (mode or "certifi").strip().lower()
    if mode in ("system", "os", "native"):
        return ssl.create_default_context()
    if mode in ("none", "off", "insecure"):
        return False
    return True


class GitHubClient:
    def __init__(
        self,
        *,
        timeout: int = 15,
        user_agent: str = "InterviewReviewBot/1.0 (+personal use)",
        token: str | None = None,
        spacing_sec: int = 0,
        ssl_mode: str | None = None,
    ) -> None:
        self.spacing_sec = spacing_sec
        self._verify = resolve_ssl_verify(ssl_mode or GITHUB_SSL_MODE)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=self._verify,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/vnd.github+json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        self._fetch_options = {
            "timeout": timeout,
            "follow_redirects": True,
            "headers": {"User-Agent": user_agent, "Accept": "text/plain, */*"},
        }
        self.fetch_client = self._new_fetch_client()
        self._previous_fetch_clients: list[httpx.Client] = []

    def _new_fetch_client(self) -> httpx.Client:
        # 独立连接池：对网络不稳定的 raw 域名在 socket 层重试连接失败，
        # 避免单次连接被重置就让整个文件失败（文件级仍受 max_retries 约束）。
        # 显式绑定 IPv4：部分网络下 raw.githubusercontent.com 的 AAAA 记录
        # 不可达，而系统按 IPv6 优先逐个等待连接超时，单文件可耗时 80s+。
        return httpx.Client(
            transport=httpx.HTTPTransport(
                retries=FETCH_SOCKET_RETRIES,
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
                local_address="0.0.0.0",
                verify=self._verify,
            ),
            **self._fetch_options,
        )

    def reset_fetch_connection(self) -> None:
        """丢弃连接池，下一文件重新建连。

        旧连接池里可能还挂着复用连接，主网络不稳时复用连接会先经历
        长读等待才报错；旧池延迟到 close() 再关闭，避免此处阻塞。
        """
        self._previous_fetch_clients.append(self.fetch_client)
        self.fetch_client = self._new_fetch_client()

    def close(self) -> None:
        self.fetch_client.close()
        for stale in self._previous_fetch_clients:
            stale.close()
        self.client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _get(self, url: str) -> httpx.Response:
        response = self.client.get(url)
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            raise ApiError(
                429,
                "RATE_LIMITED",
                "GitHub API 限流，请配置 GITHUB_TOKEN 或稍后重试",
            )
        return response

    def _default_branch(self, target: GitHubTarget) -> str:
        response = self._get(
            f"https://api.github.com/repos/{target.owner}/{target.repo}"
        )
        if response.status_code != 200:
            raise ApiError(
                400,
                "CRAWL_FAILED",
                f"无法读取仓库信息：HTTP {response.status_code}",
            )
        return response.json().get("default_branch") or "main"

    def list_files(self, target: GitHubTarget, max_files: int) -> list[str]:
        ref = target.ref or self._default_branch(target)
        if target.path.lower().endswith((".md", ".markdown")):
            return [
                "https://raw.githubusercontent.com/"
                f"{target.owner}/{target.repo}/{quote(ref, safe='')}/"
                f"{quote(target.path, safe='/')}"
            ]
        tree_url = (
            f"https://api.github.com/repos/{target.owner}/{target.repo}"
            f"/git/trees/{quote(ref, safe='')}?recursive=1"
        )
        response = self._get(tree_url)
        if response.status_code != 200:
            raise ApiError(
                400,
                "CRAWL_FAILED",
                f"无法读取仓库文件树：HTTP {response.status_code}",
            )
        data = response.json()
        if data.get("truncated"):
            # 超大仓库只取 API 返回的前一部分，并记录日志。
            pass
        prefix = target.path.strip("/")
        urls: list[str] = []
        for item in data.get("tree") or []:
            if item.get("type") != "blob":
                continue
            path = item.get("path") or ""
            if not path.lower().endswith((".md", ".markdown")):
                continue
            if prefix and not (path == prefix or path.startswith(prefix + "/")):
                continue
            urls.append(
                "https://raw.githubusercontent.com/"
                f"{target.owner}/{target.repo}/{quote(ref, safe='')}/"
                f"{quote(path, safe='/')}"
            )
            if len(urls) >= max_files:
                break
        return urls

    def fetch_text(self, url: str) -> tuple[int, str]:
        response = self.fetch_client.get(url)
        if response.status_code != 200:
            return response.status_code, ""
        content = response.content
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("文件超过 2MB 限制")
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return response.status_code, content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("无法识别文件编码")


def _spaced_source(source: CrawlSource) -> bool:
    """默认 UA 的源才做间隔与连接保活；自定义 UA 的源行为保持调用方原样。"""
    return (source.user_agent or "").startswith(USER_AGENT_PREFIX)


def _log(log: list[str], message: str) -> None:
    log.append(f"{utcnow().isoformat()}Z {message}")


def _limit_fetch_timeout(
    client: GitHubClient, timeout_sec: int, deadline: float | None = None
) -> None:
    """把单次请求超时压到文件剩余时限内；仅真实客户端需要，测试替身跳过。"""
    fetch_client = getattr(client, "fetch_client", None)
    if fetch_client is None:
        return
    remaining = deadline if deadline is not None else time.monotonic() + timeout_sec
    fetch_client.timeout = httpx.Timeout(
        _remaining_timeout(timeout_sec, remaining),
        connect=min(10, timeout_sec),
    )


def _maybe_refresh_connection(client: GitHubClient) -> None:
    """文件间停顿较长时旧连接多半已被中途设备回收，主动重建，
    否则下一个文件会先撞上坏死连接（尤其在主网络不通、仅 IPv6 可达时）。"""
    if getattr(client, "spacing_sec", 0) >= KEEPALIVE_EXPIRY:
        client.reset_fetch_connection()


def run_task(task_id: int, token: str | None = None) -> None:
    """后台线程入口：执行一次采集任务。"""
    with session_scope() as db:
        task = db.get(CrawlTask, task_id)
        if task is None:
            return
        source = db.get(CrawlSource, task.source_id)
        if source is None:
            task.status = "failed"
            task.log = "源不存在"
            task.finished_at = utcnow()
            return
        if source.source_kind != "github":
            task.status = "failed"
            task.log = "M1 仅支持 GitHub 采集，牛客爬虫将在 M2 提供"
            task.finished_at = utcnow()
            return

        task.status = "running"
        task.started_at = utcnow()
        log: list[str] = []
        task.log = ""
        db.commit()

        try:
            target = parse_github_source(source.url)
            existing = db.scalars(
                select(CrawlTaskFile)
                .where(CrawlTaskFile.task_id == task.id)
                .order_by(CrawlTaskFile.id)
            ).all()
            if existing:
                file_rows = list(existing)
                _log(log, f"重试任务：使用已有 {len(file_rows)} 个文件记录")
            else:
                with GitHubClient(
                    timeout=source.timeout_sec,
                    user_agent=source.user_agent,
                    token=token,
                ) as client:
                    urls = client.list_files(target, source.max_files_per_run)
                _log(log, f"发现 {len(urls)} 个 Markdown 文件")
                if not urls:
                    log.append("没有可采集的 Markdown 文件")
                file_rows = []
                for url in urls:
                    row = CrawlTaskFile(task_id=task.id, url=url, status="pending")
                    db.add(row)
                    file_rows.append(row)
                db.flush()
                task.total_files = len(file_rows)
                db.commit()

            success = 0
            failed = 0
            spaced = _spaced_source(source)
            with GitHubClient(
                timeout=source.timeout_sec,
                user_agent=source.user_agent,
                token=token,
                spacing_sec=source.interval_sec if spaced else 0,
            ) as client:
                _limit_fetch_timeout(client, source.timeout_sec)
                cache_dir = DATA_DIR / "crawl_cache" / str(task.id)
                cache_dir.mkdir(parents=True, exist_ok=True)
                for index, row in enumerate(file_rows):
                    if row.status == "success":
                        success += 1
                        continue
                    row.status = "running"
                    db.commit()
                    last_error = ""
                    deadline = time.monotonic() + FILE_DEADLINE_FACTOR * source.timeout_sec
                    for attempt in range(max(1, source.max_retries)):
                        if time.monotonic() >= deadline:
                            last_error = last_error or "超过文件处理时限"
                            _log(log, f"跳过剩余重试 {row.url}：已达文件时限")
                            break
                        try:
                            _limit_fetch_timeout(client, source.timeout_sec, deadline)
                            status, text = client.fetch_text(row.url)
                            row.http_status = status
                            if status != 200:
                                raise ValueError(f"HTTP {status}")
                            text, cleaned = clean_source_text(text)
                            if cleaned:
                                _log(log, f"清洗 {row.url}：{len(cleaned)} 行广告/水印/纯符号")
                            parsed = parse_markdown(text)
                            outcome = ingest_parse_result(
                                db,
                                parsed,
                                source_type="crawler",
                                origin_prefix=row.url,
                                crawl_task_id=task.id,
                                source_id=source.id,
                                origin_is_url=True,
                            )
                            parsed_count = len(parsed.questions) + len(parsed.knowledge)
                            cache_path = cache_dir / f"{index:04d}.md"
                            cache_path.write_text(text, encoding="utf-8")
                            row.cached_path = str(cache_path)
                            row.parsed_count = parsed_count
                            row.status = "success"
                            row.fetched_at = utcnow()
                            row.error = None
                            success += 1
                            _log(
                                log,
                                f"成功 {row.url}，解析 {parsed_count} 条，待审 {outcome.pending_created}，重复 {outcome.duplicates}",
                            )
                            for error in parsed.errors[:5]:
                                _log(log, f"解析警告 {row.url}: {error}")
                            last_error = ""
                            break
                        except Exception as exc:  # noqa: BLE001
                            last_error = f"{type(exc).__name__}: {exc}"
                            if attempt + 1 < source.max_retries:
                                time.sleep(2**attempt)
                    if last_error:
                        failed += 1
                        row.status = "failed"
                        row.error = last_error
                        _log(log, f"失败 {row.url}: {last_error}")
                    db.commit()
                    _maybe_refresh_connection(client)
                    if not spaced:
                        # 自定义 UA 的调用方保持原有间隔语义。
                        if source.interval_sec >= MIN_INTERVAL:
                            time.sleep(source.interval_sec)
                    elif source.interval_sec < MIN_INTERVAL:
                        time.sleep(MIN_INTERVAL)

            task.success_files = success
            task.failed_files = failed
            if success == 0 and failed > 0:
                task.status = "failed"
            elif failed > 0:
                task.status = "partial"
            else:
                task.status = "success"
            task.log = "\n".join(log)
            task.finished_at = utcnow()
            source.last_run_at = utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            _log(log, f"任务异常：{type(exc).__name__}: {exc}")
            task.status = "failed"
            task.log = "\n".join(log)
            task.finished_at = utcnow()
            db.commit()


def mark_running_tasks_failed() -> int:
    with session_scope() as db:
        rows = db.scalars(
            select(CrawlTask).where(CrawlTask.status == "running")
        ).all()
        for task in rows:
            task.status = "failed"
            task.log = (task.log or "") + "\n服务重启，running 任务标记为 failed"
            task.finished_at = utcnow()
        return len(rows)
