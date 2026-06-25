from __future__ import annotations

import random


def random_token(prefix: str) -> str:
    return f"{prefix}{random.randint(10000, 99999)}"  # nosec B311


def request_path(*, sender_name: str, handle_token: str) -> str:
    return f"/org/freedesktop/portal/desktop/request/{sender_name}/{handle_token}"


def unwrap_variant(value: object) -> object:
    return value.value if hasattr(value, "value") else value
