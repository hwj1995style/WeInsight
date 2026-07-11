from __future__ import annotations

from app.rpa.interfaces import VisibleMessage


class FakeDesktopClient:
    def __init__(self, version: str = "4.1.8.107", logged_in: bool = True) -> None:
        self.version = version
        self.logged_in = logged_in
        self.screenshots: list[str] = []

    def get_client_version(self) -> str:
        return self.version

    def check_login_status(self) -> bool:
        return self.logged_in

    def save_screenshot(self, path: str) -> str:
        self.screenshots.append(path)
        return path


class FakeGroupRpaClient:
    def __init__(self, messages: list[VisibleMessage]) -> None:
        self.messages = messages
        self.opened_groups: list[str] = []
        self.scroll_count = 0

    def open_group(self, group_name: str) -> None:
        self.opened_groups.append(group_name)

    def read_visible_messages(self) -> list[VisibleMessage]:
        return list(self.messages)

    def scroll_up_messages(self, pages: int = 1) -> None:
        self.scroll_count += pages


