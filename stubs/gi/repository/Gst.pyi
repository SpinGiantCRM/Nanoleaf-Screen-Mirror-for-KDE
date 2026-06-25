from enum import IntEnum
from typing import Any

class State(IntEnum):
    NULL = 0
    PLAYING = 1

class StateChangeReturn(IntEnum):
    FAILURE = 0

class MapFlags(IntEnum):
    READ = 1

def init(args: Any) -> None: ...
def parse_launch(pipeline_desc: str) -> Any: ...
