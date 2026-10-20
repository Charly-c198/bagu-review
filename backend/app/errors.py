"""统一响应包与 API 异常。"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str = "",
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.data = data


def ok(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"code": "OK", "data": data, "message": message}
