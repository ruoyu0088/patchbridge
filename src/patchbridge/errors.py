from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An expected, user-facing error.

    Every API handler converts this into a structured JSON response.  Internal
    exceptions are logged and converted by the global handler as well.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            body["details"] = self.details
        return body
