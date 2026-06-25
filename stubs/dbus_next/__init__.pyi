from collections.abc import Callable
from enum import IntEnum
from typing import Any

class MessageType(IntEnum):
    METHOD_CALL = 1
    METHOD_RETURN = 2
    ERROR = 3
    SIGNAL = 4

class Message:
    message_type: MessageType
    error_name: str | None
    body: list[Any]
    path: str
    interface: str
    member: str
    unix_fds: list[int]
    def __init__(
        self,
        *,
        destination: str = ...,
        path: str = ...,
        interface: str = ...,
        member: str = ...,
        signature: str = ...,
        body: list[Any] | None = ...,
        unix_fds: list[int] | None = ...,
    ) -> None: ...

class Variant:
    def __init__(self, signature: str, value: Any) -> None: ...
    signature: str
    value: Any

class BaseProxyObject:
    def get_interface(self, name: str) -> ProxyInterface: ...

class ProxyInterface:
    def __getattr__(self, name: str) -> Any: ...
    async def call_pick_color(self, parent_window: str, options: dict[str, Variant]) -> str: ...
    def on_Response(self, callback: Callable[..., None]) -> None: ...
