"""
Shared runtime state passed between main orchestrator and the web UI.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable


@dataclass
class CameraState:
    sn: str
    name: str
    online: bool
    onvif_port: int
    rtsp_path: str


@dataclass
class ProxyState:
    cameras: list[CameraState] = field(default_factory=list)
    connected: bool = False
    error: str | None = None
    last_refresh: datetime | None = None
    # Callback that main.py registers so the web UI can trigger a reinitialise
    reinit_callback: Callable[[], Awaitable[None]] | None = None
