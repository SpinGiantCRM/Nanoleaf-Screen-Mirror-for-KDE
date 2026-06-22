from __future__ import annotations

from typing import Any


def stretch_menu_width(menu: Any, *, min_width: int = 220) -> None:
    actions = list(getattr(menu, "actions", lambda: [])())
    if not actions:
        set_min = getattr(menu, "setMinimumWidth", None)
        if callable(set_min):
            set_min(int(min_width))
        return
    font_metrics_fn = getattr(menu, "fontMetrics", None)
    metrics = font_metrics_fn() if callable(font_metrics_fn) else None
    widest = 0
    for action in actions:
        text = str(getattr(action, "text", lambda: "")() or "")
        if metrics is not None and hasattr(metrics, "horizontalAdvance"):
            width = int(metrics.horizontalAdvance(text))
        else:
            width = len(text) * 8
        menu_obj = getattr(action, "menu", lambda: None)()
        if menu_obj is not None:
            stretch_menu_width(menu_obj, min_width=min_width)
            sub_min = int(getattr(menu_obj, "minimumWidth", lambda: min_width)() or min_width)
            width = max(width, sub_min - 32)
        widest = max(widest, width)
    computed = max(int(min_width), widest + 48)
    set_min = getattr(menu, "setMinimumWidth", None)
    if callable(set_min):
        set_min(computed)


def stretch_combo_popup(combo: Any) -> None:
    view = combo.view()
    if view is None:
        return
    width = int(combo.width() or 0)
    if width > 0:
        set_min = getattr(view, "setMinimumWidth", None)
        if callable(set_min):
            set_min(width)


def stretch_all_combo_popups(root: Any) -> None:
    find_children = getattr(root, "findChildren", None)
    if not callable(find_children):
        return
    combo_type = type(getattr(root, "display_preset_combo", object()))
    for combo in find_children(combo_type):
        stretch_combo_popup(combo)


def mark_compact(button: Any) -> None:
    set_prop = getattr(button, "setProperty", None)
    if callable(set_prop):
        set_prop("compact", True)
    style = getattr(button, "style", lambda: None)()
    unpolish = getattr(style, "unpolish", None) if style is not None else None
    polish = getattr(style, "polish", None) if style is not None else None
    if callable(unpolish) and callable(polish):
        unpolish(button)
        polish(button)


def mark_primary(button: Any) -> None:
    set_prop = getattr(button, "setProperty", None)
    if callable(set_prop):
        set_prop("primary", True)
    style = getattr(button, "style", lambda: None)()
    unpolish = getattr(style, "unpolish", None) if style is not None else None
    polish = getattr(style, "polish", None) if style is not None else None
    if callable(unpolish) and callable(polish):
        unpolish(button)
        polish(button)


def mark_heading(label: Any) -> None:
    set_prop = getattr(label, "setProperty", None)
    if callable(set_prop):
        set_prop("heading", True)
    style = getattr(label, "style", lambda: None)()
    unpolish = getattr(style, "unpolish", None) if style is not None else None
    polish = getattr(style, "polish", None) if style is not None else None
    if callable(unpolish) and callable(polish):
        unpolish(label)
        polish(label)


def mark_muted(label: Any) -> None:
    set_prop = getattr(label, "setProperty", None)
    if callable(set_prop):
        set_prop("muted", True)
    style = getattr(label, "style", lambda: None)()
    unpolish = getattr(style, "unpolish", None) if style is not None else None
    polish = getattr(style, "polish", None) if style is not None else None
    if callable(unpolish) and callable(polish):
        unpolish(label)
        polish(label)
