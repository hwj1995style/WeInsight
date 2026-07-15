from __future__ import annotations

from enum import Enum


class WechatHealthStatus(str, Enum):
    OK = "ok"
    NOT_RUNNING = "not_running"
    NOT_FOUND = "not_running"
    NOT_LOGGED_IN = "not_logged_in"
    VERSION_MISMATCH = "version_mismatch"
    WINDOW_UNAVAILABLE = "window_unavailable"
    RPA_UNAVAILABLE = "rpa_unavailable"
