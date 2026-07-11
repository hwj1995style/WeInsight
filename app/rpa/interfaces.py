from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VisibleMessage:
    group_name: str
    sender_name: str
    msg_time_display: str
    msg_content: str
    msg_type: str = "text"


class WechatDesktopClient(Protocol):
    def get_client_version(self) -> str:
        ...

    def check_login_status(self) -> bool:
        ...

    def save_screenshot(self, path: str) -> str:
        ...


class WechatGroupRpaClient(Protocol):
    def open_group(self, group_name: str) -> None:
        ...

    def read_visible_messages(self) -> list[VisibleMessage]:
        ...

    def scroll_up_messages(self, pages: int = 1) -> None:
        ...

