from typing import Any


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        error: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        self.extra = extra or {}

