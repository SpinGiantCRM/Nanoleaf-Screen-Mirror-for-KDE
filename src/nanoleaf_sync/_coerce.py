"""Small runtime coercion helpers for typed config/diagnostic payloads."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

RGBTuple = tuple[int, int, int]


def as_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def as_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return default
    return default


def as_optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def as_rgb_tuple3(values: Sequence[object]) -> RGBTuple:
    if len(values) < 3:
        return (0, 0, 0)
    return (as_int(values[0]), as_int(values[1]), as_int(values[2]))


def as_side_counts4(values: Iterable[int]) -> tuple[int, int, int, int]:
    items = [int(v) for v in values]
    if len(items) != 4:
        raise ValueError("side counts require exactly four values")
    return (items[0], items[1], items[2], items[3])


def scalar_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, (bool, list)):
        return default
    return as_float(value, default=default)


def scalar_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, (bool, list)):
        return default
    return as_int(value, default=default)
