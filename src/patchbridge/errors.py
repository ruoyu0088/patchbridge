from __future__ import annotations

from typing import Any

from .i18n import tr


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
            "message": tr(self.message),
        }
        if self.details is not None:
            body["details"] = _localize_value(self.details)
        return body


def _localize_value(value: Any) -> Any:
    if isinstance(value, str):
        return tr(value)
    if isinstance(value, list):
        return [_localize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_localize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _localize_value(item) for key, item in value.items()}
    return value
