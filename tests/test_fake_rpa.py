from __future__ import annotations

from app.rpa.fake_clients import FakeDesktopClient, FakeGroupRpaClient
from app.rpa.interfaces import VisibleMessage


def test_fake_desktop_client_reports_version_and_screenshot() -> None:
    client = FakeDesktopClient(version="4.1.8.107", logged_in=True)

    assert client.get_client_version() == "4.1.8.107"
    assert client.check_login_status() is True
    assert client.save_screenshot("logs/screenshots/a.png") == "logs/screenshots/a.png"
    assert client.screenshots == ["logs/screenshots/a.png"]


def test_fake_group_client_reads_messages() -> None:
    message = VisibleMessage(
        group_name="核心群A",
        sender_name="张三",
        msg_time_display="08:31",
        msg_content="求购鸡蛋",
    )
    client = FakeGroupRpaClient(messages=[message])

    client.open_group("核心群A")
    client.scroll_up_messages(2)

    assert client.opened_groups == ["核心群A"]
    assert client.scroll_count == 2
    assert client.read_visible_messages() == [message]


