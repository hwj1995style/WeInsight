import sys
from types import SimpleNamespace

import pytest

from app.rpa.wxauto_client import WxautoGroupRpaClient, WxautoNotAvailableError


class FakeWx:
    def __init__(self) -> None:
        self.chats: list[str] = []
        self.scrolls = 0

    def ChatWith(self, name: str) -> None:
        self.chats.append(name)

    def GetAllMessage(self):
        return [{"sender": "Alice", "content": "hello", "time": "10:00"}]

    def ScrollUp(self) -> None:
        self.scrolls += 1


def test_wxauto_group_client_normalizes_messages() -> None:
    wx = FakeWx()
    client = WxautoGroupRpaClient(wx=wx)
    client.open_group("群聊")
    message = client.read_visible_messages()[0]
    assert (message.group_name, message.sender_name, message.msg_content) == ("群聊", "Alice", "hello")


def test_wxauto_group_client_scrolls_requested_pages() -> None:
    wx = FakeWx()
    WxautoGroupRpaClient(wx=wx).scroll_up_messages(3)
    assert wx.scrolls == 3


def test_wxauto_group_client_retries_transient_chat_switch_failure(monkeypatch) -> None:
    class FlakyWx:
        def __init__(self): self.attempts = 0
        def ChatWith(self, name):
            self.attempts += 1
            if self.attempts < 3: raise RuntimeError("transient UIA failure")
    wx = FlakyWx(); sleeps = []
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", sleeps.append)
    WxautoGroupRpaClient(wx=wx).open_group("核心群A")
    assert wx.attempts == 3
    assert sleeps == [1.0, 1.0]


def test_wxauto_group_client_prefers_wxauto4_adapter(monkeypatch) -> None:
    calls = []
    class FakeWeChat4:
        def __init__(self, **kwargs): calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=FakeWeChat4))
    monkeypatch.setitem(sys.modules, "wxauto", SimpleNamespace(WeChat=lambda: pytest.fail("legacy adapter used")))
    assert isinstance(WxautoGroupRpaClient().wx, FakeWeChat4)
    assert calls == [{"ads": False}]


def test_wxauto_group_client_retries_wxauto4_after_preparing_chat_page(monkeypatch) -> None:
    attempts = []; prepares = []
    class FakeWeChat4:
        def __init__(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1: raise AttributeError("GroupControl unavailable")
    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=FakeWeChat4))
    monkeypatch.setattr(WxautoGroupRpaClient, "_prepare_wechat_chat_page", staticmethod(lambda: prepares.append(True)))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda _: None)
    assert isinstance(WxautoGroupRpaClient().wx, FakeWeChat4)
    assert len(attempts) == 2 and prepares == [True]


def test_wxauto_group_client_uses_bounded_initialization_retry(monkeypatch) -> None:
    attempts = []; prepares = []
    class BrokenWeChat4:
        def __init__(self, **kwargs): attempts.append(kwargs); raise RuntimeError("broken")
    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=BrokenWeChat4))
    monkeypatch.setattr(WxautoGroupRpaClient, "_prepare_wechat_chat_page", staticmethod(lambda: prepares.append(True)))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda _: None)
    with pytest.raises(WxautoNotAvailableError, match="initialization failed"):
        WxautoGroupRpaClient()
    assert len(attempts) == 3 and len(prepares) == 2


def test_wxauto_group_client_wraps_legacy_adapter_initialization_failure(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "wxauto4", None)
    monkeypatch.setitem(sys.modules, "wxauto", SimpleNamespace(WeChat=lambda: (_ for _ in ()).throw(RuntimeError("invalid handle"))))
    with pytest.raises(WxautoNotAvailableError, match="invalid handle"):
        WxautoGroupRpaClient()
