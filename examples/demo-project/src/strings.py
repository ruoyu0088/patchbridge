"""Small string helpers for the demo project."""


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def truncate(value: str, limit: int = 40) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"
