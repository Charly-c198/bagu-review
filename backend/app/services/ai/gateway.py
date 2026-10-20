"""M3a AI 网关：OpenAI 兼容接口、重试、缓存、预算与 JSON Schema 校验。

设计约束：
- 未配置 / 超时 / 限流 / 上游 5xx 都表现为可降级的 ApiError，绝不阻塞核心流程。
- 每次真实调用记录 token、耗时、状态；默认不保存输入输出原文。
- 调用外部 API 前先结束数据库读写事务，避免 SQLite 写锁被慢请求拉长。
"""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import config
from ...errors import ApiError
from ...models import AiCache, AiCall
from ...utils.timeutil import utcnow

logger = logging.getLogger("bajiu.ai")

MAX_RETRIES = 2
REPAIR_ATTEMPTS = 1


@dataclass(frozen=True)
class AIConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_sec: int = 60
    max_input_chars: int = 8000
    max_output_tokens: int = 2000
    monthly_token_limit: int = 1_000_000
    cache_ttl_days: int = 30
    price_input_per_1k: float = 0.0
    price_output_per_1k: float = 0.0
    json_mode: str = "auto"
    ssl_mode: str = "certifi"

    @classmethod
    def from_env(cls) -> "AIConfig":
        return cls(
            base_url=config.AI_BASE_URL,
            api_key=config.AI_API_KEY,
            model=config.AI_MODEL,
            timeout_sec=config.AI_TIMEOUT_SEC,
            max_input_chars=config.AI_MAX_INPUT_CHARS,
            max_output_tokens=config.AI_MAX_OUTPUT_TOKENS,
            monthly_token_limit=config.AI_MONTHLY_TOKEN_LIMIT,
            cache_ttl_days=config.AI_CACHE_TTL_DAYS,
            price_input_per_1k=config.AI_PRICE_INPUT_PER_1K,
            price_output_per_1k=config.AI_PRICE_OUTPUT_PER_1K,
            json_mode=config.AI_JSON_MODE,
            ssl_mode=config.AI_SSL_MODE,
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"


class _Retryable(Exception):
    """可重试的上游错误。"""


def _resolve_verify(mode: str | None) -> bool | ssl.SSLContext:
    mode = (mode or "certifi").strip().lower()
    if mode in ("system", "os", "native"):
        return ssl.create_default_context()
    if mode in ("none", "off", "insecure"):
        return False
    return True


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


def _month_start():
    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class AIGateway:
    def __init__(
        self,
        db: Session,
        config_obj: AIConfig | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.db = db
        self.config = config_obj or AIConfig.from_env()
        self._transport = transport
        self._client: httpx.Client | None = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "AIGateway":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    self.config.timeout_sec,
                    connect=min(10, self.config.timeout_sec),
                ),
                verify=_resolve_verify(self.config.ssl_mode),
                transport=self._transport,
            )
        return self._client

    # ---- 对外入口 -----------------------------------------------------

    def complete_json(
        self,
        *,
        purpose: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema_model: type[BaseModel],
        prompt_version_id: int | None,
        cache_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.configured:
            raise ApiError(
                503,
                "AI_NOT_CONFIGURED",
                "AI 未配置：请设置 BAJIU_AI_BASE_URL / BAJIU_AI_API_KEY / BAJIU_AI_MODEL",
            )

        cache_key = self._cache_key(
            purpose, prompt_version_id, cache_input if cache_input is not None else payload
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            self._record_call(
                purpose=purpose,
                prompt_version_id=prompt_version_id,
                status="cache_hit",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
            )
            return cached

        self._check_budget()
        # 结束读事务后再发网络请求，避免慢请求拉长 SQLite 事务。
        self.db.commit()

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ]
        started = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        raw = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw, in_tokens, out_tokens = self._post(messages)
            except _Retryable as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(min(2**attempt, 4))
                    continue
                self._record_call(
                    purpose=purpose,
                    prompt_version_id=prompt_version_id,
                    status="failed",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error_code="AI_UNAVAILABLE",
                )
                raise ApiError(
                    503,
                    "AI_UNAVAILABLE",
                    "AI 服务暂不可用，请稍后重试或转人工质检",
                ) from exc
            except ApiError:
                self._record_call(
                    purpose=purpose,
                    prompt_version_id=prompt_version_id,
                    status="failed",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error_code="AI_UNAVAILABLE",
                )
                raise
            input_tokens += in_tokens
            output_tokens += out_tokens
            break

        for repair in range(REPAIR_ATTEMPTS + 1):
            try:
                data = _parse_json(raw)
                validated = schema_model.model_validate(data)
            except (ValueError, ValidationError) as exc:
                if repair < REPAIR_ATTEMPTS:
                    messages.append({"role": "assistant", "content": raw})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "上一次输出不是合法 JSON 或不符合 Schema。"
                                "请只返回符合 Schema 的 JSON 对象，不要代码块或解释。"
                            ),
                        }
                    )
                    try:
                        raw, in_tokens, out_tokens = self._post(messages)
                    except _Retryable as post_exc:
                        self._record_call(
                            purpose=purpose,
                            prompt_version_id=prompt_version_id,
                            status="failed",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            error_code="AI_UNAVAILABLE",
                        )
                        raise ApiError(
                            503,
                            "AI_UNAVAILABLE",
                            "AI 服务暂不可用，请稍后重试或转人工质检",
                        ) from post_exc
                    except ApiError:
                        self._record_call(
                            purpose=purpose,
                            prompt_version_id=prompt_version_id,
                            status="failed",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            error_code="AI_UNAVAILABLE",
                        )
                        raise
                    input_tokens += in_tokens
                    output_tokens += out_tokens
                    continue
                self._record_call(
                    purpose=purpose,
                    prompt_version_id=prompt_version_id,
                    status="failed",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error_code="AI_SCHEMA_INVALID",
                )
                raise ApiError(
                    502,
                    "AI_SCHEMA_INVALID",
                    "AI 返回格式不合法，已记录为失败，可重试或转人工质检",
                ) from exc

            result = validated.model_dump(mode="json")
            self._record_call(
                purpose=purpose,
                prompt_version_id=prompt_version_id,
                status="success",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            self._write_cache(cache_key, prompt_version_id, result)
            return result

        # 理论上不可达；保留兜底避免静态检查报错。
        raise ApiError(502, "AI_SCHEMA_INVALID", "AI 返回格式不合法")

    # ---- HTTP ---------------------------------------------------------

    def _post(self, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": self.config.max_output_tokens,
        }
        if self.config.json_mode != "off":
            body["response_format"] = {"type": "json_object"}
        response = self._request(body)
        if (
            response.status_code == 400
            and "response_format" in body
            and self.config.json_mode == "auto"
        ):
            body.pop("response_format", None)
            response = self._request(body)
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise _Retryable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ApiError(
                503,
                "AI_UNAVAILABLE",
                f"AI 服务返回 HTTP {response.status_code}，请检查配置或稍后重试",
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _Retryable("AI 响应结构不完整") from exc
        if not isinstance(content, str) or not content.strip():
            raise _Retryable("AI 返回空内容")
        usage = payload.get("usage") or {}
        return (
            content,
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )

    def _request(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self.client.post(
                self.config.chat_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.TransportError as exc:
            raise _Retryable(str(exc)) from exc

    # ---- 缓存 / 预算 / 记录 -------------------------------------------

    def _cache_key(
        self,
        purpose: str,
        prompt_version_id: int | None,
        payload: dict[str, Any],
    ) -> str:
        material = {
            "purpose": purpose,
            "prompt_version_id": prompt_version_id,
            "model": self.config.model,
            "payload": payload,
        }
        text = json.dumps(material, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.db.get(AiCache, cache_key)
        if row is None:
            return None
        if row.expires_at <= utcnow():
            self.db.delete(row)
            self.db.commit()
            return None
        try:
            data = json.loads(row.response_json)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_cache(
        self,
        cache_key: str,
        prompt_version_id: int | None,
        result: dict[str, Any],
    ) -> None:
        expires_at = utcnow() + timedelta(days=max(1, self.config.cache_ttl_days))
        row = self.db.get(AiCache, cache_key)
        if row is None:
            self.db.add(
                AiCache(
                    cache_key=cache_key,
                    prompt_version_id=prompt_version_id,
                    response_json=json.dumps(result, ensure_ascii=False),
                    expires_at=expires_at,
                )
            )
        else:
            row.response_json = json.dumps(result, ensure_ascii=False)
            row.prompt_version_id = prompt_version_id
            row.expires_at = expires_at
        self.db.commit()

    def _check_budget(self) -> None:
        limit = self.config.monthly_token_limit
        if limit <= 0:
            return
        used = (
            self.db.scalar(
                select(
                    func.coalesce(
                        func.sum(AiCall.input_tokens + AiCall.output_tokens), 0
                    )
                ).where(
                    AiCall.created_at >= _month_start(),
                    AiCall.status.in_(("success", "failed")),
                )
            )
            or 0
        )
        if int(used) >= limit:
            raise ApiError(
                429,
                "AI_BUDGET_EXCEEDED",
                "本月 AI token 预算已用完，可继续使用人工质检",
            )

    def _record_call(
        self,
        *,
        purpose: str,
        prompt_version_id: int | None,
        status: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error_code: str | None = None,
    ) -> None:
        cost = (
            input_tokens / 1000 * self.config.price_input_per_1k
            + output_tokens / 1000 * self.config.price_output_per_1k
        )
        self.db.add(
            AiCall(
                purpose=purpose,
                prompt_version_id=prompt_version_id,
                model=self.config.model,
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                cost=round(cost, 6),
                latency_ms=max(0, latency_ms),
                status=status,
                error_code=error_code,
            )
        )
        self.db.commit()


def get_ai_gateway(db: Session) -> AIGateway:
    return AIGateway(db)
