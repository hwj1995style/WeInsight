from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pytest

from app.rpa.wxauto_client import (
    NoSameDayArticleAvailable,
    WxautoArticleRpaClient,
    WxautoGroupRpaClient,
    WxautoNotAvailableError,
    _find_main_search_result,
    _focus_main_search_edit,
    _history_row_click_coords,
)


class FakeWx:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def ChatWith(self, group_name: str) -> None:
        self.opened.append(group_name)

    def GetAllMessage(self):
        return [
            ("张三", "求购鸡蛋 30 箱", "08:31"),
            {"sender": "李四", "content": "供应鸡蛋 20 箱", "time": "08:32", "type": "text"},
        ]


class FakeArticleWx:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def ChatWith(self, account_name: str) -> None:
        self.opened.append(account_name)

    def GetAllMessage(self):
        return [
            (
                "订阅号",
                "第一篇 https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz",
                "09:00",
            ),
            {
                "sender": "订阅号",
                "content": "重复 https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz",
                "time": "09:01",
            },
            SimpleNamespace(
                content="第二篇 https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1&sn=uvw"
            ),
        ]


class FakeRouteCacheRepo:
    def __init__(self, route=None) -> None:
        self.route = route
        self.successes = []
        self.failures = []

    def get_active_route(self, account_name: str):
        return self.route

    def upsert_success(self, **kwargs):
        self.successes.append(kwargs)

    def mark_failure(self, **kwargs):
        self.failures.append(kwargs)


class FakeRoute:
    account_name = "行业观察"
    route_type = "visible_text"
    entry_label = None
    entry_index = None
    link_extract_type = "visible_text"


class RaisingRouteCacheRepo(FakeRouteCacheRepo):
    def get_active_route(self, account_name: str):
        raise RuntimeError("cache backend unavailable")


class FlakyChatWx:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.opened: list[str] = []
        self.attempts = 0

    def ChatWith(self, name: str) -> None:
        self.attempts += 1
        if self.attempts <= self.failures_before_success:
            raise RuntimeError("transient UIA COM failure")
        self.opened.append(name)


def test_wxauto_group_client_normalizes_messages() -> None:
    wx = FakeWx()
    client = WxautoGroupRpaClient(wx=wx, current_group_name="核心群A")

    client.open_group("核心群A")
    messages = client.read_visible_messages()

    assert wx.opened == ["核心群A"]
    assert messages[0].sender_name == "张三"
    assert messages[0].msg_content == "求购鸡蛋 30 箱"
    assert messages[1].sender_name == "李四"
    assert messages[1].msg_time_display == "08:32"


def test_wxauto_group_client_retries_transient_chat_switch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FlakyChatWx(failures_before_success=2)
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: sleep_calls.append(seconds))
    client = WxautoGroupRpaClient(wx=wx)

    client.open_group("核心群A")

    assert wx.opened == ["核心群A"]
    assert wx.attempts == 3
    assert sleep_calls == [1.0, 1.0]


def test_wxauto_article_client_extracts_limited_unique_article_links() -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(wx=wx, link_extract_methods=("visible_text",))

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=2)

    assert wx.opened == ["行业观察"]
    assert links == [
        "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz",
        "https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1&sn=uvw",
    ]


def test_wxauto_article_client_retries_transient_chat_switch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FlakyChatWx(failures_before_success=2)
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: sleep_calls.append(seconds))
    client = WxautoArticleRpaClient(wx=wx)

    client.open_public_account("行业观察")

    assert wx.opened == ["行业观察"]
    assert wx.attempts == 3
    assert sleep_calls == [1.0, 1.0]


def test_wxauto_article_client_uses_short_retry_window_beyond_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FlakyChatWx(failures_before_success=4)
    sleep_calls: list[float] = []
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: sleep_calls.append(seconds))
    client = WxautoArticleRpaClient(wx=wx)

    client.open_public_account("行业观察")

    assert wx.opened == ["行业观察"]
    assert wx.attempts == 5
    assert sleep_calls == [1.0, 1.0, 1.0, 1.0]


def test_wxauto_article_client_uses_search_fallback_when_chatwith_does_not_open_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(wx=wx, open_account_search_fallback_enabled=True)
    fallback_calls: list[str] = []
    wait_results = iter([False, True])

    monkeypatch.setattr(
        client,
        "_wait_for_public_account_window",
        lambda account_name: next(wait_results),
    )
    monkeypatch.setattr(
        client,
        "_open_public_account_from_main_search",
        lambda account_name: fallback_calls.append(account_name) or True,
    )

    client.open_public_account("信立鸡蛋当日价格")

    assert wx.opened == ["信立鸡蛋当日价格"]
    assert fallback_calls == ["信立鸡蛋当日价格"]
    assert client.current_account_name == "信立鸡蛋当日价格"


def test_wxauto_article_client_waits_for_account_window_before_search_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        open_account_search_fallback_enabled=True,
    )
    visibility = iter([False, False, True])
    sleep_calls: list[float] = []

    monkeypatch.setattr(client, "_public_account_window_visible", lambda account_name: next(visibility))
    monkeypatch.setattr(
        client,
        "_open_public_account_from_main_search",
        lambda account_name: pytest.fail("search fallback should not run while the account window is loading"),
    )
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    client.open_public_account("信立鸡蛋当日价格")

    assert sleep_calls == [0.2, 0.2]
    assert client.current_account_name == "信立鸡蛋当日价格"


def test_wxauto_article_client_waits_for_account_window_after_search_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        open_account_search_fallback_enabled=True,
    )
    fallback_calls: list[str] = []
    wait_calls: list[str] = []
    wait_results = iter([False, True])

    monkeypatch.setattr(
        client,
        "_wait_for_public_account_window",
        lambda account_name: wait_calls.append(account_name) or next(wait_results),
    )
    monkeypatch.setattr(
        client,
        "_open_public_account_from_main_search",
        lambda account_name: fallback_calls.append(account_name) or True,
    )

    client.open_public_account("信立鸡蛋当日价格")

    assert fallback_calls == ["信立鸡蛋当日价格"]
    assert wait_calls == ["信立鸡蛋当日价格", "信立鸡蛋当日价格"]
    assert client.current_account_name == "信立鸡蛋当日价格"


def test_open_public_account_does_not_use_network_search_after_direct_search_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        open_account_search_fallback_enabled=True,
    )
    monkeypatch.setattr(client, "_wait_for_public_account_window", lambda account_name: False)
    monkeypatch.setattr(client, "_open_public_account_from_main_search", lambda account_name: False)

    with pytest.raises(RuntimeError, match="public account window not found"):
        client.open_public_account("一箱蛋")

    assert not hasattr(client, "_open_public_account_from_network_search")


class FakeDirectSearchRect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def width(self) -> int:
        return self.right - self.left

    def height(self) -> int:
        return self.bottom - self.top


class FakeDirectSearchControl:
    def __init__(self, *, text: str, class_name: str, left: int, top: int) -> None:
        self._text = text
        self._class_name = class_name
        self.element_info = SimpleNamespace(class_name=class_name, control_type="ListItem")
        self._rect = FakeDirectSearchRect(left, top, left + 300, top + 60)

    def window_text(self) -> str:
        return self._text

    def class_name(self) -> str:
        return self._class_name

    def friendly_class_name(self) -> str:
        return "ListItem"

    def rectangle(self) -> FakeDirectSearchRect:
        return self._rect


class FakeDirectSearchWindow:
    def __init__(self, controls: list[FakeDirectSearchControl]) -> None:
        self._controls = controls

    def descendants(self):
        return self._controls

    def rectangle(self) -> FakeDirectSearchRect:
        return FakeDirectSearchRect(0, 0, 800, 1000)


class FakeSearchEdit:
    def __init__(self, *, has_focus: bool) -> None:
        self._has_focus = has_focus
        self.focus_calls = 0

    def set_focus(self) -> None:
        self.focus_calls += 1

    def has_keyboard_focus(self) -> bool:
        return self._has_focus


class FakeFocusWindow:
    def set_focus(self) -> None:
        return None


def test_find_main_search_result_prefers_exact_public_account_candidate() -> None:
    public_account = FakeDirectSearchControl(
        text="一箱蛋",
        class_name="mmui::SearchContentCellView",
        left=90,
        top=120,
    )
    chat_record = FakeDirectSearchControl(
        text="一箱蛋",
        class_name="mmui::XTableCell",
        left=90,
        top=260,
    )

    assert _find_main_search_result(FakeDirectSearchWindow([chat_record, public_account]), "一箱蛋") is public_account


def test_find_main_search_result_rejects_partial_name() -> None:
    partial = FakeDirectSearchControl(
        text="一箱蛋每日行情",
        class_name="mmui::SearchContentCellView",
        left=90,
        top=120,
    )

    assert _find_main_search_result(FakeDirectSearchWindow([partial]), "一箱蛋") is None


def test_focus_main_search_edit_returns_false_without_keyboard_focus() -> None:
    search_edit = FakeSearchEdit(has_focus=False)

    assert _focus_main_search_edit(FakeFocusWindow(), search_edit) is False
    assert search_edit.focus_calls == 1


def test_copy_latest_article_links_returns_empty_for_no_same_day_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    repo = FakeRouteCacheRepo(
        route=SimpleNamespace(
            route_type="probe",
            link_extract_type="copy_link_menu",
            entry_label=None,
            entry_index=None,
        )
    )
    client = WxautoArticleRpaClient(
        wx=wx,
        route_cache_repo=repo,
        link_extract_methods=("copy_link_menu", "uia_value", "visible_text"),
    )
    copy_calls: list[str] = []

    monkeypatch.setattr(
        client,
        "_prepare_browser_route_for_current_account",
        lambda: (_ for _ in ()).throw(NoSameDayArticleAvailable("no same-day article")),
    )
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: copy_calls.append("copy") or [],
    )

    client.open_public_account("上海禽蛋价格综合报价")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == []
    assert copy_calls == []
    assert repo.failures == []


def test_copy_latest_article_links_prefers_copy_link_menu_before_uia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu", "uia_value", "visible_text"),
    )
    calls: list[str] = []

    def copy_menu(max_articles: int):
        calls.append("copy_link_menu")
        return ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]

    def uia(max_articles: int):
        calls.append("uia_value")
        return []

    monkeypatch.setattr(client, "_copy_link_menu_article_links", copy_menu)
    monkeypatch.setattr(client, "_uia_value_article_links", uia)
    monkeypatch.setattr(client, "_prepare_browser_route_for_current_account", lambda: None)

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert calls == ["copy_link_menu"]


def test_copy_latest_article_links_uses_uia_value_when_copy_menu_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu", "uia_value"),
    )

    monkeypatch.setattr(client, "_copy_link_menu_article_links", lambda max_articles: [])
    monkeypatch.setattr(
        client,
        "_uia_value_article_links",
        lambda max_articles: ["https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1&sn=uvw"],
    )
    monkeypatch.setattr(client, "_prepare_browser_route_for_current_account", lambda: None)

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1&sn=uvw"]


def test_copy_latest_article_links_opens_history_entries_before_non_visible_extractors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu",),
    )
    calls: list[str] = []

    def open_candidates() -> None:
        calls.append("open_history_entry_candidates")

    def copy_menu(max_articles: int):
        calls.append("copy_link_menu")
        return ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]

    monkeypatch.setattr(client, "_open_history_entry_candidates", open_candidates)
    monkeypatch.setattr(client, "_copy_link_menu_article_links", copy_menu)
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]
    assert calls == ["open_history_entry_candidates", "copy_link_menu"]


def test_copy_latest_article_links_closes_browser_after_non_visible_extractor_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu",),
        close_browser_after_extract=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(client, "_open_history_entry_candidates", lambda: calls.append("open"))
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: calls.append("copy") or ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"],
    )
    monkeypatch.setattr(client, "_close_large_browser_windows", lambda: calls.append("close"))
    monkeypatch.setattr(client, "_close_current_account_window", lambda: calls.append("close_account"))

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]
    assert calls == ["close", "open", "copy", "close", "close_account"]


def test_copy_latest_article_links_closes_account_window_after_browser_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu",),
        close_browser_after_extract=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(client, "_open_history_entry_candidates", lambda: calls.append("open"))
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: calls.append("copy") or ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"],
    )
    monkeypatch.setattr(client, "_close_large_browser_windows", lambda: calls.append("close_browser"))
    monkeypatch.setattr(client, "_close_current_account_window", lambda: calls.append("close_account"))

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]
    assert calls == ["close_browser", "open", "copy", "close_browser", "close_account"]


def test_copy_latest_article_links_reopens_history_even_when_stale_detail_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu",),
        close_browser_after_extract=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(client, "_close_large_browser_windows", lambda: calls.append("close"))
    monkeypatch.setattr(client, "_close_current_account_window", lambda: calls.append("close_account"))
    monkeypatch.setattr(client, "_open_history_entry_candidates", lambda: calls.append("open"))
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: calls.append("copy") or ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"],
    )

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]
    assert calls == ["close", "open", "copy", "close", "close_account"]


def test_copy_latest_article_links_reopens_history_for_cached_browser_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    route = FakeRoute()
    route.link_extract_type = "copy_link_menu"
    repo = FakeRouteCacheRepo(route=route)
    client = WxautoArticleRpaClient(
        wx=wx,
        route_cache_repo=repo,
        close_browser_after_extract=True,
    )
    calls: list[str] = []

    monkeypatch.setattr(client, "_close_large_browser_windows", lambda: calls.append("close"))
    monkeypatch.setattr(client, "_close_current_account_window", lambda: calls.append("close_account"))
    monkeypatch.setattr(client, "_open_history_entry_candidates", lambda: calls.append("open"))
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: calls.append("copy") or ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"],
    )

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=3&idx=1&sn=def"]
    assert calls == ["close", "open", "copy", "close", "close_account"]


def test_copy_latest_article_links_does_not_close_browser_for_visible_text_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("visible_text",),
        close_browser_after_extract=True,
    )
    close_calls: list[str] = []

    monkeypatch.setattr(client, "_close_large_browser_windows", lambda: close_calls.append("close"))

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert close_calls == []


def test_copy_link_menu_article_links_reads_clipboard_from_lazy_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clipboard = {"value": "original"}
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(wx=wx)
    clicked: list[str] = []

    def paste() -> str:
        return clipboard["value"]

    def copy(value: str) -> None:
        clipboard["value"] = value

    def click_copy_link_menu_item() -> None:
        clicked.append("clicked")
        clipboard["value"] = "https://mp.weixin.qq.com/s?__biz=abc&mid=9&idx=1&sn=lazy"

    monkeypatch.setitem(sys.modules, "pyperclip", SimpleNamespace(paste=paste, copy=copy))
    monkeypatch.setattr(client, "_click_copy_link_menu_item", click_copy_link_menu_item)

    links = client._copy_link_menu_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=9&idx=1&sn=lazy"]
    assert clicked == ["clicked"]
    assert clipboard["value"] == "original"


def test_uia_value_article_links_reads_large_browser_control_values_from_lazy_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, value: str) -> None:
            self.iface_value = SimpleNamespace(CurrentValue=value)

    class FakeWindow:
        def __init__(self, class_name: str, rect: FakeRect, values: list[str]) -> None:
            self._class_name = class_name
            self._rect = rect
            self._controls = [FakeControl(value) for value in values]

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return self._controls

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [
                FakeWindow(
                    "Chrome_WidgetWin_1",
                    FakeRect(0, 0, 1200, 900),
                    [
                        "https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=uia",
                        "https://mp.weixin.qq.com/s?__biz=abc&mid=8&idx=1&sn=uia2",
                    ],
                ),
                FakeWindow(
                    "Chrome_WidgetWin_1",
                    FakeRect(0, 0, 900, 650),
                    ["https://mp.weixin.qq.com/s?__biz=abc&mid=99&idx=1&sn=small"],
                ),
            ]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    links = client._uia_value_article_links(max_articles=2)

    assert links == [
        "https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=uia",
        "https://mp.weixin.qq.com/s?__biz=abc&mid=8&idx=1&sn=uia2",
    ]


def test_browser_detail_window_visible_ignores_article_url_outside_address_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, value: str, rect: FakeRect, control_type: str = "Text") -> None:
            self.iface_value = SimpleNamespace(CurrentValue=value)
            self._rect = rect
            self._control_type = control_type
            self.element_info = SimpleNamespace(control_type=control_type, class_name="")

        def rectangle(self) -> FakeRect:
            return self._rect

        def friendly_class_name(self) -> str:
            return self._control_type

    class FakeBrowserWindow:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_1")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_1"

        def rectangle(self) -> FakeRect:
            return FakeRect(0, 0, 1200, 900)

        def descendants(self):
            return [
                FakeControl(
                    "https://mp.weixin.qq.com/mp/profile_ext?action=home",
                    FakeRect(100, 20, 900, 60),
                    "Edit",
                ),
                FakeControl(
                    "https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=listrow",
                    FakeRect(300, 400, 1000, 460),
                ),
            ]

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [FakeBrowserWindow()]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._browser_detail_window_visible() is False


def test_browser_detail_window_visible_uses_top_address_bar_article_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, value: str, rect: FakeRect, control_type: str = "Edit") -> None:
            self.iface_value = SimpleNamespace(CurrentValue=value)
            self._rect = rect
            self._control_type = control_type
            self.element_info = SimpleNamespace(control_type=control_type, class_name="")

        def rectangle(self) -> FakeRect:
            return self._rect

        def friendly_class_name(self) -> str:
            return self._control_type

    class FakeBrowserWindow:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_1")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_1"

        def rectangle(self) -> FakeRect:
            return FakeRect(0, 0, 1200, 900)

        def descendants(self):
            return [
                FakeControl(
                    "https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=current",
                    FakeRect(100, 20, 900, 60),
                )
            ]

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [FakeBrowserWindow()]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._browser_detail_window_visible() is True


def test_browser_detail_window_visible_uses_document_article_url_with_publish_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            value: str = "",
            name: str = "",
            rect: FakeRect,
            control_type: str,
        ) -> None:
            self.iface_value = SimpleNamespace(CurrentValue=value) if value else None
            self._name = name
            self._rect = rect
            self._control_type = control_type
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                class_name="",
            )

        def rectangle(self) -> FakeRect:
            return self._rect

        def friendly_class_name(self) -> str:
            return self._control_type

        def window_text(self) -> str:
            return self._name

    class FakeBrowserWindow:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_0"

        def rectangle(self) -> FakeRect:
            return FakeRect(80, 45, 1860, 1140)

        def descendants(self):
            return [
                FakeControl(
                    value="https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=current",
                    rect=FakeRect(90, 98, 1854, 1132),
                    control_type="Document",
                ),
                FakeControl(
                    name="2026年7月9日 09:11",
                    rect=FakeRect(810, 179, 997, 204),
                    control_type="Static",
                ),
            ]

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [FakeBrowserWindow()]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._browser_detail_window_visible(target_date=date(2026, 7, 9)) is True


def test_browser_detail_window_visible_requires_target_publish_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            value: str = "",
            name: str = "",
            rect: FakeRect | None = None,
            control_type: str = "Text",
        ) -> None:
            self.iface_value = SimpleNamespace(CurrentValue=value) if value else None
            self._name = name
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._control_type = control_type
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                class_name="",
            )

        def rectangle(self) -> FakeRect:
            return self._rect

        def friendly_class_name(self) -> str:
            return self._control_type

        def window_text(self) -> str:
            return self._name

    class FakeBrowserWindow:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_1")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_1"

        def rectangle(self) -> FakeRect:
            return FakeRect(0, 0, 1200, 900)

        def descendants(self):
            return [
                FakeControl(
                    value="https://mp.weixin.qq.com/s?__biz=abc&mid=7&idx=1&sn=current",
                    rect=FakeRect(100, 20, 900, 60),
                    control_type="Edit",
                ),
                FakeControl(
                    name="作者 2026年7月8日 00:00 广东",
                    rect=FakeRect(320, 120, 900, 160),
                ),
            ]

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [FakeBrowserWindow()]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._browser_detail_window_visible(target_date=date(2026, 7, 9)) is False
    assert client._browser_detail_window_visible(target_date=date(2026, 7, 8)) is True


def test_copy_latest_article_links_does_not_copy_when_browser_detail_date_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(
        wx=wx,
        link_extract_methods=("copy_link_menu",),
    )
    copied: list[str] = []

    monkeypatch.setattr(
        client,
        "_prepare_browser_route_for_current_account",
        lambda: (_ for _ in ()).throw(RuntimeError("browser detail publish date is not today")),
    )
    monkeypatch.setattr(
        client,
        "_copy_link_menu_article_links",
        lambda max_articles: copied.append("copy") or ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"],
    )

    client.open_public_account("行业观察")

    with pytest.raises(RuntimeError, match="publish date"):
        client.copy_latest_article_links(max_articles=1)

    assert copied == []


def test_open_history_entry_candidates_accepts_large_browser_window_without_url_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rpa.wxauto_client as wxauto_client

    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            automation_id: str = "",
            value: str | None = None,
            on_click=None,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._on_click = on_click
            self._descendants = descendants or []
            self.iface_value = SimpleNamespace(CurrentValue=value) if value is not None else None
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._on_click is not None:
                self._on_click(coords)

    state = {
        "browser_visible": False,
        "detail_visible": False,
        "route_clicked": False,
        "row_clicked": False,
    }

    def mark_route_clicked(_coords=None) -> None:
        state["route_clicked"] = True
        state["browser_visible"] = True

    def mark_row_clicked(_coords=None) -> None:
        state["row_clicked"] = True
        state["detail_visible"] = True

    route_button = FakeControl(
        name="历史消息",
        control_type="Button",
        rect=FakeRect(40, 520, 180, 560),
        on_click=mark_route_clicked,
    )
    account_history_row = FakeControl(
        name="第1条",
        control_type="ListItem",
        rect=FakeRect(60, 260, 380, 320),
        on_click=mark_row_clicked,
    )
    account_window = FakeControl(
        name="行业观察",
        class_name="mmui::ChatSingleWindow",
        rect=FakeRect(0, 0, 420, 640),
        descendants=[route_button, account_history_row],
    )
    today = date.today()
    browser_history_row = FakeControl(
        name=f"继续上涨：{today.month}月{today.day}日贵阳鸡蛋价格参考",
        control_type="ListItem",
        rect=FakeRect(420, 390, 1200, 450),
        on_click=mark_row_clicked,
    )

    class FakeBrowserWindow(FakeControl):
        def __init__(self) -> None:
            super().__init__(
                class_name="Chrome_WidgetWin_1",
                rect=FakeRect(200, 40, 1600, 980),
            )

        def descendants(self):
            if state["detail_visible"]:
                return [
                    FakeControl(
                        value="https://mp.weixin.qq.com/s?__biz=abc&mid=8&idx=1&sn=guiyang",
                        control_type="Edit",
                        rect=FakeRect(420, 55, 1200, 90),
                    ),
                    FakeControl(
                        name=f"作者 {today.year}年{today.month}月{today.day}日 05:06 湖北",
                        control_type="Text",
                        rect=FakeRect(420, 120, 1200, 155),
                    ),
                ]
            return [
                browser_history_row,
                FakeControl(
                    value="not a wechat article url",
                    control_type="Edit",
                    rect=FakeRect(420, 55, 1200, 90),
                ),
            ]

    browser_window = FakeBrowserWindow()

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            windows = [account_window]
            if state["browser_visible"]:
                windows.append(browser_window)
            return windows

    class FakeTime:
        def __init__(self) -> None:
            self.current = 100.0

        def time(self) -> float:
            self.current += 0.1
            return self.current

        def sleep(self, seconds: float) -> None:
            self.current += seconds

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(wxauto_client, "time", FakeTime())
    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    client.open_public_account("行业观察")

    client._open_history_entry_candidates()

    assert state["route_clicked"] is True
    assert state["row_clicked"] is True


def test_click_route_entry_label_prefers_uia_invoke_over_physical_click() -> None:
    class FakeControl:
        def __init__(self) -> None:
            self.invoked = False
            self.clicked = False
            self.element_info = SimpleNamespace(name="蛋价资讯", control_type="Button")

        def window_text(self) -> str:
            return "蛋价资讯"

        def friendly_class_name(self) -> str:
            return "Button"

        def invoke(self) -> None:
            self.invoked = True

        def click_input(self, coords=None) -> None:
            self.clicked = True
            raise AssertionError("physical click should not be used when invoke is available")

    class FakeAccountWindow:
        def __init__(self, control: FakeControl) -> None:
            self.control = control

        def descendants(self):
            return [self.control]

    control = FakeControl()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._click_route_entry_label(FakeAccountWindow(control)) is True
    assert control.invoked is True
    assert control.clicked is False


def test_click_route_entry_label_uses_win32_fallback_when_click_input_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        left = 10
        top = 20
        right = 110
        bottom = 120

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self) -> None:
            self.element_info = SimpleNamespace(name="蛋价资讯", control_type="Button")

        def window_text(self) -> str:
            return "蛋价资讯"

        def friendly_class_name(self) -> str:
            return "Button"

        def rectangle(self) -> FakeRect:
            return FakeRect()

        def click_input(self, coords=None) -> None:
            raise OSError("SetCursorPos failed")

    class FakeAccountWindow:
        def __init__(self, control: FakeControl) -> None:
            self.control = control

        def descendants(self):
            return [self.control]

    events: list[object] = []

    class FakeWin32Api:
        @staticmethod
        def SetCursorPos(coords):
            events.append(("pos", coords))

        @staticmethod
        def mouse_event(event, dx, dy, data, extra):
            events.append(("mouse", event, dx, dy, data, extra))

    monkeypatch.setitem(sys.modules, "win32api", FakeWin32Api)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(MOUSEEVENTF_LEFTDOWN=2, MOUSEEVENTF_LEFTUP=4),
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._click_route_entry_label(FakeAccountWindow(FakeControl())) is True
    assert events == [
        ("pos", (60, 70)),
        ("mouse", 2, 0, 0, 0, 0),
        ("mouse", 4, 0, 0, 0, 0),
    ]


def test_click_route_entry_label_uses_win32_fallback_when_invoke_pattern_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        left = 10
        top = 20
        right = 110
        bottom = 120

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self) -> None:
            self.element_info = SimpleNamespace(name="蛋价资讯", control_type="Button")

        def window_text(self) -> str:
            return "蛋价资讯"

        def friendly_class_name(self) -> str:
            return "Button"

        def rectangle(self) -> FakeRect:
            return FakeRect()

        @property
        def iface_invoke(self):
            raise RuntimeError("NoPatternInterfaceError")

        def click_input(self, coords=None) -> None:
            raise OSError("SetCursorPos failed")

    class FakeAccountWindow:
        def descendants(self):
            return [FakeControl()]

    events: list[object] = []

    class FakeWin32Api:
        @staticmethod
        def SetCursorPos(coords):
            events.append(("pos", coords))

        @staticmethod
        def mouse_event(event, dx, dy, data, extra):
            events.append(("mouse", event, dx, dy, data, extra))

    monkeypatch.setitem(sys.modules, "win32api", FakeWin32Api)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(MOUSEEVENTF_LEFTDOWN=2, MOUSEEVENTF_LEFTUP=4),
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert client._click_route_entry_label(FakeAccountWindow()) is True
    assert events[0] == ("pos", (60, 70))


def test_find_large_browser_window_ignores_non_wechat_chrome_widget_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeWindow:
        def __init__(self, *, title: str, process_id: int) -> None:
            self._title = title
            self._process_id = process_id
            self.element_info = SimpleNamespace(class_name="Chrome_WidgetWin_1")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_1"

        def window_text(self) -> str:
            return self._title

        def rectangle(self) -> FakeRect:
            return FakeRect(0, 0, 1400, 900)

        def process_id(self) -> int:
            return self._process_id

    codex_window = FakeWindow(title="Codex", process_id=100)
    wechat_browser_window = FakeWindow(title="一箱蛋", process_id=200)

    class FakeDesktop:
        def windows(self):
            return [codex_window, wechat_browser_window]

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def name(self) -> str:
            return {100: "Codex.exe", 200: "Weixin.exe"}[self.pid]

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=FakeProcess))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    window = client._find_large_browser_window(FakeDesktop())

    assert window is wechat_browser_window


def test_find_large_browser_window_accepts_compact_wechat_app_ex_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        left = 585
        top = 70
        right = 1335
        bottom = 1070

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeWindow:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0")

        def class_name(self) -> str:
            return "Chrome_WidgetWin_0"

        def window_text(self) -> str:
            return "公众号"

        def rectangle(self) -> FakeRect:
            return FakeRect()

        def process_id(self) -> int:
            return 300

    class FakeDesktop:
        def windows(self):
            return [FakeWindow()]

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def name(self) -> str:
            assert self.pid == 300
            return "WeChatAppEx.exe"

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=FakeProcess))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    window = client._find_large_browser_window(FakeDesktop())

    assert window is not None


def test_find_first_history_row_prefers_topmost_visible_candidate() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str,
            control_type: str,
            rect: FakeRect,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect
            self._descendants = descendants or []
            self.element_info = SimpleNamespace(name=name, control_type=control_type)

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

    offscreen = FakeControl(
        name="offscreen",
        control_type="ListItem",
        rect=FakeRect(-260, 250, -20, 320),
    )
    lower_row = FakeControl(
        name="lower",
        control_type="ListItem",
        rect=FakeRect(60, 340, 360, 410),
    )
    top_row = FakeControl(
        name="top",
        control_type="ListItem",
        rect=FakeRect(55, 240, 355, 300),
    )
    tiny = FakeControl(
        name="tiny",
        control_type="ListItem",
        rect=FakeRect(70, 260, 150, 280),
    )
    account_window = FakeControl(
        name="行业观察",
        control_type="Window",
        rect=FakeRect(0, 0, 420, 640),
        descendants=[lower_row, offscreen, tiny, top_row],
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(account_window)

    assert row is top_row


def test_find_first_history_row_keeps_top_article_card_near_chat_title() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str,
            control_type: str,
            class_name: str,
            rect: FakeRect,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._class_name = class_name
            self._rect = rect
            self._descendants = descendants or []
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

    top_article_card = FakeControl(
        name="",
        control_type="ListItem",
        class_name="mmui::ChatAppReaderItemView",
        rect=FakeRect(586, 171, 1333, 492),
    )
    lower_image_card = FakeControl(
        name="图片",
        control_type="ListItem",
        class_name="mmui::ChatBubbleReferItemView",
        rect=FakeRect(586, 543, 1333, 876),
    )
    account_window = FakeControl(
        name="河北馆陶鸡蛋报价",
        control_type="Window",
        class_name="mmui::ChatSingleWindow",
        rect=FakeRect(586, 170, 1333, 970),
        descendants=[top_article_card, lower_image_card],
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(account_window)

    assert row is top_article_card


def test_find_first_history_row_prefers_quote_image_card_over_lower_ad_card() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str,
            control_type: str,
            class_name: str,
            rect: FakeRect,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._class_name = class_name
            self._rect = rect
            self._descendants = descendants or []
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

    quote_title = FakeControl(
        name="2026年7月9日湖北家美鲜鸡蛋报价",
        control_type="Text",
        class_name="Static",
        rect=FakeRect(160, 420, 520, 445),
    )
    quote_image_card = FakeControl(
        name="图片",
        control_type="Button",
        class_name="mmui::Image",
        rect=FakeRect(145, 260, 610, 452),
        descendants=[quote_title],
    )
    lower_ad_card = FakeControl(
        name="夏季蛋鸡反复拉稀？肠道不好，高产全白搭！90%养鸡人都忽略的隐形减产元凶！（广告位）",
        control_type="ListItem",
        class_name="mmui::ChatAppReaderItemView",
        rect=FakeRect(150, 463, 605, 568),
    )
    account_window = FakeControl(
        name="家美鲜鸡蛋 佳美鲜",
        control_type="Window",
        class_name="mmui::ChatSingleWindow",
        rect=FakeRect(0, 95, 750, 768),
        descendants=[lower_ad_card, quote_image_card],
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(account_window)

    assert row is quote_image_card


def test_history_row_click_coords_targets_first_article_in_tall_combo_card() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        element_info = SimpleNamespace(class_name="mmui::ChatAppReaderItemView")

        def class_name(self) -> str:
            return "mmui::ChatAppReaderItemView"

        def rectangle(self) -> FakeRect:
            return FakeRect(586, 415, 1333, 877)

    coords = _history_row_click_coords(FakeControl())

    assert coords is not None
    assert coords[0] == 373
    assert coords[1] < 120


def test_find_first_history_row_skips_article_card_scrolled_above_window() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str,
            control_type: str,
            class_name: str,
            rect: FakeRect,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._class_name = class_name
            self._rect = rect
            self._descendants = descendants or []
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

    scrolled_article_card = FakeControl(
        name="",
        control_type="ListItem",
        class_name="mmui::ChatAppReaderItemView",
        rect=FakeRect(586, -98, 1333, 364),
    )
    visible_article_card = FakeControl(
        name="",
        control_type="ListItem",
        class_name="mmui::ChatAppReaderItemView",
        rect=FakeRect(586, 415, 1333, 877),
    )
    account_window = FakeControl(
        name="家美鲜鸡蛋 佳美鲜",
        control_type="Window",
        class_name="mmui::ChatSingleWindow",
        rect=FakeRect(586, 170, 1333, 970),
        descendants=[scrolled_article_card, visible_article_card],
    )
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(account_window)

    assert row is visible_article_card


def test_find_account_window_requires_expected_account_name_when_set() -> None:
    class FakeWindow:
        def __init__(self, *, name: str, class_name: str) -> None:
            self._name = name
            self._class_name = class_name
            self.element_info = SimpleNamespace(name=name, class_name=class_name)

        def window_text(self) -> str:
            return self._name

        def class_name(self) -> str:
            return self._class_name

    class FakeDesktop:
        def windows(self):
            return [FakeWindow(name="别的公众号", class_name="mmui::ChatSingleWindow")]

    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        current_account_name="行业观察",
    )

    assert client._find_account_window(FakeDesktop()) is None


def test_find_account_window_requires_exact_normalized_account_name_match() -> None:
    class FakeWindow:
        def __init__(self, *, name: str, class_name: str) -> None:
            self._name = name
            self._class_name = class_name
            self.element_info = SimpleNamespace(name=name, class_name=class_name)

        def window_text(self) -> str:
            return self._name

        def class_name(self) -> str:
            return self._class_name

    exact_window = FakeWindow(name="  行业观察  ", class_name="mmui::ChatSingleWindow")
    partial_overlap_window = FakeWindow(name="行业观察日报", class_name="mmui::ChatSingleWindow")

    class FakeDesktop:
        def windows(self):
            return [partial_overlap_window, exact_window]

    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        current_account_name="行业观察",
    )

    assert client._find_account_window(FakeDesktop()) is exact_window


def test_find_account_container_does_not_fall_back_to_main_window_current_chat() -> None:
    class FakeWindow:
        def __init__(self, *, name: str, class_name: str) -> None:
            self._name = name
            self._class_name = class_name
            self.element_info = SimpleNamespace(name=name, class_name=class_name)

        def window_text(self) -> str:
            return self._name

        def class_name(self) -> str:
            return self._class_name

    main_window = FakeWindow(name="微信", class_name="mmui::MainWindow")

    class FakeDesktop:
        def windows(self):
            return [main_window]

    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        current_account_name="福建闽融鸡蛋报价平台",
    )

    assert client._find_account_container(FakeDesktop()) is None


def test_open_history_entry_candidates_does_not_click_main_window_group_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rpa.wxauto_client as wxauto_client

    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeGroupCard:
        def __init__(self) -> None:
            self.clicked = False
            self.element_info = SimpleNamespace(
                class_name="mmui::ChatBubbleReferItemView",
                control_type="ListItem",
            )

        def rectangle(self) -> FakeRect:
            return FakeRect(360, 240, 780, 360)

        def window_text(self) -> str:
            return "群消息里的文章卡片"

        def friendly_class_name(self) -> str:
            return "ListItem"

        def class_name(self) -> str:
            return "mmui::ChatBubbleReferItemView"

        def click_input(self, coords=None) -> None:
            self.clicked = True

    class FakeMainWindow:
        element_info = SimpleNamespace(class_name="mmui::MainWindow")

        def class_name(self) -> str:
            return "mmui::MainWindow"

        def rectangle(self) -> FakeRect:
            return FakeRect(0, 0, 900, 1000)

        def window_text(self) -> str:
            return "微信"

        def descendants(self):
            return [group_card]

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def windows(self):
            return []

        def windows(self):
            return [FakeMainWindow()]

    group_card = FakeGroupCard()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    client.open_public_account("信立鸡蛋当日价格")

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(wxauto_client.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="current account window not found"):
        client._open_history_entry_candidates()

    assert group_card.clicked is False


def test_close_current_account_window_does_not_close_main_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWindow:
        def __init__(self, *, name: str, class_name: str) -> None:
            self._name = name
            self._class_name = class_name
            self.closed = False
            self.element_info = SimpleNamespace(name=name, class_name=class_name)

        def window_text(self) -> str:
            return self._name

        def class_name(self) -> str:
            return self._class_name

        def close(self) -> None:
            self.closed = True

    main_window = FakeWindow(name="微信", class_name="mmui::MainWindow")

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def windows(self):
            return [main_window]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(
        wx=FakeArticleWx(),
        current_account_name="福建闽融鸡蛋报价平台",
    )

    client._close_current_account_window()

    assert main_window.closed is False


def test_click_copy_link_menu_item_clicks_menu_button_and_menu_item_with_fake_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            automation_id: str = "",
            descendants: list[object] | None = None,
            clicks: list[str] | None = None,
            click_label: str = "",
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._descendants = descendants or []
            self._clicks = clicks
            self._click_label = click_label
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._clicks is not None:
                self._clicks.append(self._click_label if coords is None else f"{self._click_label}:{coords}")

    clicks: list[str] = []
    menu_button = FakeControl(
        name="更多",
        control_type="Button",
        rect=FakeRect(1200, 40, 1240, 80),
        automation_id="AppMenuButton",
        clicks=clicks,
        click_label="menu-button",
    )
    browser_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(100, 40, 1600, 980),
        descendants=[menu_button],
    )
    menu_item = FakeControl(
        name="复制链接",
        control_type="MenuItem",
        rect=FakeRect(1200, 90, 1320, 120),
        clicks=clicks,
        click_label="copy-link",
    )

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [browser_window, FakeControl(descendants=[menu_item])]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    client._click_copy_link_menu_item()

    assert clicks == ["menu-button", "copy-link"]


def test_click_copy_link_menu_item_ignores_unrelated_copy_link_text_and_uses_menu_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            automation_id: str = "",
            descendants: list[object] | None = None,
            clicks: list[str] | None = None,
            click_label: str = "",
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._descendants = descendants or []
            self._clicks = clicks
            self._click_label = click_label
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._clicks is not None:
                self._clicks.append(self._click_label if coords is None else f"{self._click_label}:{coords}")

    clicks: list[str] = []
    menu_button = FakeControl(
        name="更多",
        control_type="Button",
        rect=FakeRect(1200, 40, 1240, 80),
        automation_id="AppMenuButton",
        clicks=clicks,
        click_label="menu-button",
    )
    browser_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(100, 40, 1600, 980),
        descendants=[menu_button],
    )
    unrelated_window = FakeControl(
        class_name="NotBrowserWindow",
        rect=FakeRect(0, 0, 400, 300),
        descendants=[
            FakeControl(
                name="复制链接",
                control_type="Text",
                rect=FakeRect(20, 20, 120, 40),
                clicks=clicks,
                click_label="unrelated-text",
            )
        ],
    )
    menu_popup_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(1180, 80, 1360, 220),
        descendants=[
            FakeControl(
                name="复制链接",
                control_type="MenuItem",
                rect=FakeRect(1200, 90, 1320, 120),
                clicks=clicks,
                click_label="copy-link-menu",
            )
        ],
    )

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [browser_window, unrelated_window, menu_popup_window]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    client._click_copy_link_menu_item()

    assert clicks == ["menu-button", "copy-link-menu"]


def test_click_copy_link_menu_item_rejects_visible_menu_item_in_unrelated_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            automation_id: str = "",
            descendants: list[object] | None = None,
            clicks: list[str] | None = None,
            click_label: str = "",
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._descendants = descendants or []
            self._clicks = clicks
            self._click_label = click_label
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._clicks is not None:
                self._clicks.append(self._click_label if coords is None else f"{self._click_label}:{coords}")

    clicks: list[str] = []
    menu_button = FakeControl(
        name="更多",
        control_type="Button",
        rect=FakeRect(1200, 40, 1240, 80),
        automation_id="AppMenuButton",
        clicks=clicks,
        click_label="menu-button",
    )
    browser_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(100, 40, 1600, 980),
        descendants=[menu_button],
    )
    unrelated_window = FakeControl(
        class_name="NotBrowserWindow",
        rect=FakeRect(40, 40, 500, 400),
        descendants=[
            FakeControl(
                name="复制链接",
                control_type="MenuItem",
                rect=FakeRect(60, 80, 160, 110),
                clicks=clicks,
                click_label="wrong-menu-item",
            )
        ],
    )

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [browser_window, unrelated_window]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    with pytest.raises(RuntimeError, match="copy link menu item not found"):
        client._click_copy_link_menu_item()

    assert clicks == ["menu-button"]


def test_click_copy_link_menu_item_rejects_top_level_menu_outside_browser_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            automation_id: str = "",
            descendants: list[object] | None = None,
            clicks: list[str] | None = None,
            click_label: str = "",
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._descendants = descendants or []
            self._clicks = clicks
            self._click_label = click_label
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._clicks is not None:
                self._clicks.append(self._click_label if coords is None else f"{self._click_label}:{coords}")

    clicks: list[str] = []
    menu_button = FakeControl(
        name="更多",
        control_type="Button",
        rect=FakeRect(1200, 40, 1240, 80),
        automation_id="AppMenuButton",
        clicks=clicks,
        click_label="menu-button",
    )
    browser_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(100, 40, 1600, 980),
        descendants=[menu_button],
    )
    unrelated_top_level_menu = FakeControl(
        name="Desktop menu",
        control_type="Menu",
        class_name="DesktopMenuHost",
        rect=FakeRect(20, 20, 260, 140),
        descendants=[
            FakeControl(
                name="复制链接",
                control_type="MenuItem",
                rect=FakeRect(30, 50, 150, 80),
                clicks=clicks,
                click_label="wrong-top-level-menu-item",
            )
        ],
    )

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [browser_window, unrelated_top_level_menu]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    with pytest.raises(RuntimeError, match="copy link menu item not found"):
        client._click_copy_link_menu_item()

    assert clicks == ["menu-button"]


def test_click_copy_link_menu_item_falls_back_to_window_coordinates_when_menu_button_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            *,
            name: str = "",
            control_type: str = "",
            rect: FakeRect | None = None,
            class_name: str = "",
            descendants: list[object] | None = None,
            clicks: list[object] | None = None,
            click_label: str = "",
        ) -> None:
            self._name = name
            self._control_type = control_type
            self._rect = rect or FakeRect(0, 0, 0, 0)
            self._class_name = class_name
            self._descendants = descendants or []
            self._clicks = clicks
            self._click_label = click_label
            self.element_info = SimpleNamespace(
                name=name,
                control_type=control_type,
                automation_id="",
                class_name=class_name,
            )

        def window_text(self) -> str:
            return self._name

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

        def rectangle(self) -> FakeRect:
            return self._rect

        def descendants(self):
            return list(self._descendants)

        def click_input(self, coords=None) -> None:
            if self._clicks is not None:
                self._clicks.append((self._click_label, coords))

    clicks: list[object] = []
    browser_window = FakeControl(
        class_name="Chrome_WidgetWin_1",
        rect=FakeRect(100, 40, 1600, 980),
        clicks=clicks,
        click_label="browser-window",
    )
    menu_item = FakeControl(
        name="复制链接",
        control_type="MenuItem",
        rect=FakeRect(1200, 90, 1320, 120),
        clicks=clicks,
        click_label="copy-link",
    )

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            assert backend == "uia"

        def windows(self):
            return [browser_window, FakeControl(descendants=[menu_item])]

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    client._click_copy_link_menu_item()

    assert clicks == [("browser-window", (1464, 48)), ("copy-link", None)]


def test_wxauto_article_client_probe_account_returns_safe_metadata() -> None:
    wx = FakeArticleWx()
    client = WxautoArticleRpaClient(wx=wx, link_extract_methods=("visible_text",))

    result = client.probe_account("行业观察")

    assert wx.opened == ["行业观察"]
    assert result == {
        "status": "ok",
        "account_found": 1,
        "link_count": 2,
        "message": "ready",
    }


def test_wxauto_article_client_requires_visible_message_api() -> None:
    wx = SimpleNamespace(ChatWith=lambda account_name: None)
    client = WxautoArticleRpaClient(wx=wx, link_extract_methods=("visible_text",))

    client.open_public_account("行业观察")

    with pytest.raises(AttributeError, match="GetAllMessage"):
        client.copy_latest_article_links(max_articles=1)


def test_wxauto_article_client_uses_active_route_cache_for_visible_text() -> None:
    wx = FakeArticleWx()
    repo = FakeRouteCacheRepo(route=FakeRoute())
    client = WxautoArticleRpaClient(wx=wx, route_cache_repo=repo)

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert repo.successes[-1]["route_type"] == "visible_text"
    assert repo.successes[-1]["link_extract_type"] == "visible_text"


def test_wxauto_article_client_marks_cache_failure_and_reprobes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wx = FakeArticleWx()
    route = FakeRoute()
    route.link_extract_type = "copy_link_menu"
    repo = FakeRouteCacheRepo(route=route)
    client = WxautoArticleRpaClient(
        wx=wx,
        route_cache_repo=repo,
        link_extract_methods=("visible_text",),
    )
    monkeypatch.setattr(client, "_prepare_browser_route_for_current_account", lambda: None)
    monkeypatch.setattr(client, "_copy_link_menu_article_links", lambda max_articles: [])
    monkeypatch.setattr(
        client,
        "_copy_visible_text_article_links",
        lambda max_articles: ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"],
    )

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert repo.failures
    assert repo.successes[-1]["route_type"] == "visible_text"


def test_click_route_entry_label_uses_physical_click_for_biz_menu_button() -> None:
    class FakeBizMenuButton:
        element_info = SimpleNamespace(class_name="mmui::BizMenuButton")

        def __init__(self) -> None:
            self.invoked = False
            self.clicked = False

        def window_text(self) -> str:
            return "蛋价资讯"

        def invoke(self) -> None:
            self.invoked = True

        def click_input(self) -> None:
            self.clicked = True

    class FakeAccountWindow:
        def __init__(self, button: FakeBizMenuButton) -> None:
            self.button = button

        def descendants(self):
            return [self.button]

    button = FakeBizMenuButton()
    client = WxautoArticleRpaClient(wx=FakeArticleWx(), route_entry_labels=("蛋价资讯",))

    clicked = client._click_route_entry_label(FakeAccountWindow(button))

    assert clicked is True
    assert button.invoked is False
    assert button.clicked is True


def test_open_history_entry_candidates_stops_when_route_click_opens_detail_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: True)
    monkeypatch.setattr(
        client,
        "_find_first_history_row",
        lambda account_window, **kwargs: pytest.fail("should not click a history row after browser opens"),
    )

    client._open_history_entry_candidates()


def test_open_history_entry_candidates_clicks_first_row_in_browser_history_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    account_window = object()
    class FakeBrowserWindow:
        def __init__(self) -> None:
            self.focused = False

        def set_focus(self) -> None:
            self.focused = True

    browser_window = FakeBrowserWindow()
    row = FakeRow()
    containers = []
    detail_checks = iter([False, True])

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: account_window)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: browser_window)
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: False)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(
        client,
        "_find_first_history_row",
        lambda container, **kwargs: containers.append(container) or row,
    )

    client._open_history_entry_candidates()

    assert containers == [browser_window]
    assert browser_window.focused is True
    assert row.clicked is True


def test_open_history_entry_candidates_waits_for_browser_history_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rpa.wxauto_client as wxauto_client

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeTime:
        def __init__(self) -> None:
            self.current = 100.0

        def time(self) -> float:
            self.current += 0.1
            return self.current

        def sleep(self, seconds: float) -> None:
            self.current += seconds

    class FakeBrowserWindow:
        def __init__(self) -> None:
            self.focused = False

        def set_focus(self) -> None:
            self.focused = True

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    browser_window = FakeBrowserWindow()
    row = FakeRow()
    target_row_checks = {"count": 0}
    detail_checks = iter([False, True])

    def find_first_history_row(container, **kwargs):
        if kwargs.get("require_target_date"):
            target_row_checks["count"] += 1
            return row if target_row_checks["count"] >= 2 else None
        return None

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(wxauto_client, "time", FakeTime())
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: browser_window)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_find_first_history_row", find_first_history_row)

    client._open_history_entry_candidates()

    assert target_row_checks["count"] >= 2
    assert browser_window.focused is True
    assert row.clicked is True


def test_open_history_entry_candidates_requires_detail_after_browser_history_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rpa.wxauto_client as wxauto_client

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeTime:
        def __init__(self) -> None:
            self.current = 100.0

        def time(self) -> float:
            self.current += 1.0
            return self.current

        def sleep(self, seconds: float) -> None:
            self.current += seconds

    class FakeBrowserWindow:
        def set_focus(self) -> None:
            return None

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    row = FakeRow()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(wxauto_client, "time", FakeTime())
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: FakeBrowserWindow())
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: True)
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: False)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: row)

    with pytest.raises(RuntimeError, match="browser detail window not found"):
        client._open_history_entry_candidates()

    assert row.clicked is True


def test_open_history_entry_candidates_does_not_click_bottom_menu_without_history_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    bottom_menu_clicked = {"value": False}

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_first_history_row", lambda account_window, **kwargs: None)
    monkeypatch.setattr(client, "_browser_detail_window_visible", lambda **kwargs: False)
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: False)
    monkeypatch.setattr(
        client,
        "_click_bottom_menu_fallback",
        lambda account_window: bottom_menu_clicked.__setitem__("value", True) or True,
    )

    with pytest.raises(RuntimeError):
        client._open_history_entry_candidates()

    assert bottom_menu_clicked["value"] is False


def test_open_history_entry_candidates_stops_when_clicked_detail_date_is_not_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def windows(self):
            return []

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    row = FakeRow()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    def browser_detail_visible(**kwargs) -> bool:
        return kwargs.get("target_date") is None

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_container", lambda desktop: object())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: row)
    monkeypatch.setattr(client, "_wait_for_browser_detail", lambda **kwargs: False)
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: True)
    monkeypatch.setattr(client, "_browser_detail_window_visible", browser_detail_visible)
    monkeypatch.setattr(
        client,
        "_wait_for_history_row",
        lambda desktop, account_window: pytest.fail("wrong-date detail must not be scanned as history"),
    )

    with pytest.raises(RuntimeError, match="publish date"):
        client._open_history_entry_candidates()

    assert row.clicked is True


def test_open_history_entry_candidates_clicks_first_visible_browser_row_before_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rpa.wxauto_client as wxauto_client

    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def windows(self):
            return []

    class FakeBrowserWindow:
        def set_focus(self) -> None:
            return None

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    row = FakeRow()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    def find_first_history_row(container, **kwargs):
        if kwargs.get("require_target_date"):
            return None
        return row

    def browser_detail_visible(**kwargs) -> bool:
        return row.clicked and kwargs.get("target_date") is None

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(wxauto_client, "time", SimpleNamespace(time=lambda: 100.0, sleep=lambda seconds: None))
    monkeypatch.setattr(client, "_find_account_container", lambda desktop: None)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: FakeBrowserWindow())
    monkeypatch.setattr(client, "_find_first_history_row", find_first_history_row)
    monkeypatch.setattr(client, "_wait_for_browser_detail", lambda **kwargs: False)
    monkeypatch.setattr(client, "_browser_detail_window_visible", browser_detail_visible)

    with pytest.raises(NoSameDayArticleAvailable):
        client._open_history_entry_candidates()

    assert row.clicked is True


def test_open_history_entry_candidates_clicks_chat_card_before_bottom_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self) -> None:
            self.clicked = True

    account_window = object()
    row = FakeRow()
    bottom_calls: list[str] = []
    detail_checks = iter([False, True])
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: account_window)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: row)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_click_bottom_menu_fallback", lambda account_window: bottom_calls.append("bottom") or True)

    client._open_history_entry_candidates()

    assert row.clicked is True
    assert bottom_calls == []


def test_open_history_entry_candidates_uses_account_info_entry_when_no_chat_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self, coords=None) -> None:
            self.clicked = True

    account_window = object()
    row = FakeRow()
    info_calls: list[str] = []
    browser_detail_checks = iter([False, True])
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_container", lambda desktop: account_window)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: None)
    monkeypatch.setattr(client, "_click_bottom_menu_fallback", lambda account_window: False)
    monkeypatch.setattr(client, "_click_account_info_entry", lambda account_window: info_calls.append("info") or True)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(browser_detail_checks, True),
    )
    monkeypatch.setattr(client, "_wait_for_history_row", lambda desktop, account_window: (object(), row))
    monkeypatch.setattr(client, "_wait_for_browser_detail", lambda **kwargs: True)

    client._open_history_entry_candidates()

    assert info_calls == ["info"]
    assert row.clicked is True


def test_open_history_entry_candidates_uses_account_info_without_bottom_menu_when_no_chat_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeRow:
        def __init__(self) -> None:
            self.clicked = False

        def click_input(self, coords=None) -> None:
            self.clicked = True

    account_window = object()
    row = FakeRow()
    bottom_calls: list[str] = []
    info_calls: list[str] = []
    state = {"info_opened": False}
    browser_detail_checks = iter([False, True])
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    def click_account_info(_account_window):
        info_calls.append("info")
        state["info_opened"] = True
        return True

    def wait_for_history_row(_desktop, _account_window):
        assert state["info_opened"]
        return object(), row

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_container", lambda desktop: account_window)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: None)
    monkeypatch.setattr(client, "_click_bottom_menu_fallback", lambda account_window: bottom_calls.append("bottom") or True)
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: state["info_opened"])
    monkeypatch.setattr(client, "_click_account_info_entry", click_account_info)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(browser_detail_checks, True),
    )
    monkeypatch.setattr(client, "_wait_for_history_row", wait_for_history_row)
    monkeypatch.setattr(client, "_wait_for_browser_detail", lambda **kwargs: True)

    client._open_history_entry_candidates()

    assert bottom_calls == []
    assert info_calls == ["info"]
    assert row.clicked is True


def test_open_history_entry_candidates_uses_physical_click_for_chat_article_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeChatCard:
        def __init__(self) -> None:
            self.clicked = False
            self.invoked = False
            self.element_info = SimpleNamespace(class_name="mmui::ChatAppReaderItemView")

        def class_name(self) -> str:
            return "mmui::ChatAppReaderItemView"

        def invoke(self) -> None:
            self.invoked = True

        def click_input(self, coords=None) -> None:
            self.clicked = True

    card = FakeChatCard()
    detail_checks = iter([False, True])
    bottom_calls: list[str] = []
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: False)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: None)
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: card)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_click_bottom_menu_fallback", lambda account_window: bottom_calls.append("bottom") or True)

    client._open_history_entry_candidates()

    assert card.clicked is True
    assert card.invoked is False
    assert bottom_calls == []


def test_open_history_entry_candidates_uses_win32_foreground_when_browser_focus_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeBrowserWindow:
        handle = 12345

        def set_focus(self) -> None:
            raise RuntimeError("focus denied")

    class FakeRow:
        def click_input(self) -> None:
            return None

    foreground_calls = []
    detail_checks = iter([False, True])
    browser_window = FakeBrowserWindow()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(
            ShowWindow=lambda handle, command: foreground_calls.append(("show", handle, command)),
            SetForegroundWindow=lambda handle: foreground_calls.append(("foreground", handle)),
        ),
    )
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(SW_RESTORE=9))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: object())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: browser_window)
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: False)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: FakeRow())

    client._open_history_entry_candidates()

    assert ("show", 12345, 9) in foreground_calls
    assert ("foreground", 12345) in foreground_calls


def test_open_history_entry_candidates_clicks_uncovered_part_of_browser_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeAccountWindow:
        def rectangle(self) -> FakeRect:
            return FakeRect(100, 100, 400, 500)

    class FakeBrowserWindow:
        def set_focus(self) -> None:
            return None

    class FakeRow:
        def __init__(self) -> None:
            self.click_coords = None

        def rectangle(self) -> FakeRect:
            return FakeRect(50, 200, 450, 240)

        def click_input(self, coords=None) -> None:
            self.click_coords = coords

    row = FakeRow()
    detail_checks = iter([False, True])
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: FakeAccountWindow())
    monkeypatch.setattr(client, "_click_route_entry_label", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: FakeBrowserWindow())
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: False)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: row)

    client._open_history_entry_candidates()

    assert row.click_coords is not None
    assert row.click_coords[0] < 50


def test_open_history_entry_candidates_avoids_wechat_main_window_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDesktop:
        def __init__(self, backend: str) -> None:
            self.backend = backend

        def windows(self):
            return [wechat_main_window]

    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeWindow:
        def __init__(self, rect: FakeRect, class_name: str) -> None:
            self._rect = rect
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name)

        def rectangle(self) -> FakeRect:
            return self._rect

        def class_name(self) -> str:
            return self._class_name

    class FakeBrowserWindow(FakeWindow):
        def __init__(self) -> None:
            super().__init__(FakeRect(0, 50, 1695, 1140), "Chrome_WidgetWin_0")

        def set_focus(self) -> None:
            return None

    class FakeRow:
        def __init__(self) -> None:
            self.click_coords = None

        def rectangle(self) -> FakeRect:
            return FakeRect(443, 482, 1120, 513)

        def click_input(self, coords=None) -> None:
            self.click_coords = coords

    wechat_main_window = FakeWindow(FakeRect(8, 0, 790, 1140), "mmui::MainWindow")
    row = FakeRow()
    detail_checks = iter([False, True])
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_find_account_window", lambda desktop: None)
    monkeypatch.setattr(client, "_click_bottom_menu_fallback", lambda account_window: True)
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: FakeBrowserWindow())
    monkeypatch.setattr(client, "_large_browser_window_visible", lambda: False)
    monkeypatch.setattr(
        client,
        "_browser_detail_window_visible",
        lambda **kwargs: False if kwargs.get("target_date") is None else next(detail_checks, True),
    )
    monkeypatch.setattr(client, "_find_first_history_row", lambda container, **kwargs: row)

    client._open_history_entry_candidates()

    assert row.click_coords is not None
    assert row.click_coords[0] > 340


def test_find_first_history_row_accepts_static_article_title() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(
            self,
            rect: FakeRect,
            text: str = "",
            control_type: str = "",
            class_name: str = "",
        ) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

    class FakeBrowser(FakeControl):
        def descendants(self):
            return [
                FakeControl(FakeRect(440, 430, 1120, 461), "第一篇文章", "Static", "weui_media_title")
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    browser = FakeBrowser(FakeRect(0, 50, 1695, 1140))

    row = client._find_first_history_row(browser)

    assert row is not None
    assert row.window_text() == "第一篇文章"


def test_find_first_history_row_accepts_browser_row_below_profile_header() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str, control_type: str, class_name: str) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

    class FakeBrowser:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0", control_type="Window")

        def rectangle(self) -> FakeRect:
            return FakeRect(455, 48, 1302, 1080)

        def descendants(self):
            return [
                FakeControl(FakeRect(540, 126, 1220, 152), "公众号简介", "Static", "weui_media_desc"),
                FakeControl(FakeRect(692, 196, 1066, 249), "发消息", "Button", "weui_btn"),
                FakeControl(FakeRect(475, 338, 1115, 356), "8", "Static", "article__item__title"),
                FakeControl(FakeRect(475, 475, 1115, 493), "7", "Static", "article__item__title"),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(FakeBrowser(), top_only=True)

    assert row is not None
    assert row.window_text() == "8"


def test_find_first_history_row_prefers_target_date_article_title() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str, control_type: str, class_name: str) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

    class FakeBrowser(FakeControl):
        def descendants(self):
            return [
                FakeControl(
                    FakeRect(749, 430, 1072, 461),
                    "2026年7月7日上海禽蛋价格综合报价",
                    "Static",
                    "article__item__title",
                ),
                FakeControl(
                    FakeRect(749, 620, 1072, 651),
                    "2026年7月8日上海禽蛋价格综合报价",
                    "Static",
                    "article__item__title",
                ),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    browser = FakeBrowser(FakeRect(585, 70, 1335, 1070), "", "Window", "Chrome_WidgetWin_0")

    row = client._find_first_history_row(browser, target_date=date(2026, 7, 8))

    assert row is not None
    assert row.window_text() == "2026年7月8日上海禽蛋价格综合报价"


def test_find_first_history_row_treats_public_account_day_number_as_target_date() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str) -> None:
            self._rect = rect
            self._text = text
            self.element_info = SimpleNamespace(
                class_name="article__item__title",
                control_type="Static",
            )

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return "Static"

        def class_name(self) -> str:
            return "article__item__title"

    class FakeBrowser:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0", control_type="Window")

        def rectangle(self) -> FakeRect:
            return FakeRect(585, 70, 1335, 1070)

        def descendants(self):
            return [
                FakeControl(FakeRect(749, 430, 1072, 461), "7"),
                FakeControl(FakeRect(749, 620, 1072, 651), "8"),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(FakeBrowser(), target_date=date(2026, 7, 8))

    assert row is not None
    assert row.window_text() == "8"


def test_find_first_history_row_accepts_top_title_with_nearby_target_date() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str, control_type: str, class_name: str) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

    class FakeBrowser:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0", control_type="Window")

        def rectangle(self) -> FakeRect:
            return FakeRect(585, 70, 1335, 1070)

        def descendants(self):
            return [
                FakeControl(
                    FakeRect(749, 430, 1072, 461),
                    "广东东莞信立市场到货及交易价格参考",
                    "Static",
                    "article__item__title",
                ),
                FakeControl(
                    FakeRect(749, 468, 920, 496),
                    "2026年7月9日",
                    "Static",
                    "weui_media_desc",
                ),
                FakeControl(
                    FakeRect(749, 620, 1072, 651),
                    "广东东莞信立市场到货及交易价格参考",
                    "Static",
                    "article__item__title",
                ),
                FakeControl(
                    FakeRect(749, 658, 920, 686),
                    "2026年7月8日",
                    "Static",
                    "weui_media_desc",
                ),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(
        FakeBrowser(),
        target_date=date(2026, 7, 9),
        require_target_date=True,
        top_only=True,
    )

    assert row is not None
    assert row.window_text() == "广东东莞信立市场到货及交易价格参考"


def test_find_first_history_row_can_require_target_date_match() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str) -> None:
            self._rect = rect
            self._text = text
            self.element_info = SimpleNamespace(
                class_name="article__item__title",
                control_type="Static",
            )

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return "Static"

        def class_name(self) -> str:
            return "article__item__title"

    class FakeBrowser:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0", control_type="Window")

        def rectangle(self) -> FakeRect:
            return FakeRect(585, 70, 1335, 1070)

        def descendants(self):
            return [
                FakeControl(FakeRect(749, 430, 1072, 461), "8"),
                FakeControl(FakeRect(749, 620, 1072, 651), "7"),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    row = client._find_first_history_row(
        FakeBrowser(),
        target_date=date(2026, 7, 9),
        require_target_date=True,
    )

    assert row is None


def test_wait_for_history_row_returns_first_browser_history_row_for_detail_date_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str) -> None:
            self._rect = rect
            self._text = text
            self.element_info = SimpleNamespace(
                class_name="article__item__title",
                control_type="Static",
            )

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return "Static"

        def class_name(self) -> str:
            return "article__item__title"

    class FakeBrowser:
        element_info = SimpleNamespace(class_name="Chrome_WidgetWin_0", control_type="Window")

        def rectangle(self) -> FakeRect:
            return FakeRect(585, 70, 1335, 1070)

        def set_focus(self) -> None:
            return None

        def descendants(self):
            return [
                FakeControl(FakeRect(749, 430, 1072, 461), "非当天入口"),
                FakeControl(FakeRect(749, 620, 1072, 651), str(date.today().day)),
            ]

    browser = FakeBrowser()
    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    monkeypatch.setattr(client, "_find_large_browser_window", lambda desktop: browser)
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)

    browser_window, first_row = client._wait_for_history_row(object(), None, timeout_seconds=0.1)

    assert browser_window is browser
    assert first_row.window_text() == "非当天入口"


def test_find_first_history_row_prefers_article_card_over_timestamp_and_menu() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str, control_type: str, class_name: str) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

    class FakeAccountWindow(FakeControl):
        def descendants(self):
            return [
                FakeControl(FakeRect(0, 220, 700, 270), "09:25", "ListItem", "mmui::ChatItemView"),
                FakeControl(FakeRect(0, 270, 700, 520), "图片", "ListItem", "mmui::ChatBubbleReferItemView"),
                FakeControl(FakeRect(10, 900, 250, 960), "今日价格", "Button", "mmui::BizMenuButton"),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    window = FakeAccountWindow(FakeRect(0, 0, 700, 1000), "", "Window", "mmui::ChatSingleWindow")

    row = client._find_first_history_row(window)

    assert row is not None
    assert row.window_text() == "图片"


def test_find_first_history_row_ignores_main_window_left_session_list() -> None:
    class FakeRect:
        def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self) -> int:
            return self.right - self.left

        def height(self) -> int:
            return self.bottom - self.top

    class FakeControl:
        def __init__(self, rect: FakeRect, text: str, control_type: str, class_name: str) -> None:
            self._rect = rect
            self._text = text
            self._control_type = control_type
            self._class_name = class_name
            self.element_info = SimpleNamespace(class_name=class_name, control_type=control_type)

        def rectangle(self) -> FakeRect:
            return self._rect

        def window_text(self) -> str:
            return self._text

        def friendly_class_name(self) -> str:
            return self._control_type

        def class_name(self) -> str:
            return self._class_name

    class FakeMainWindow(FakeControl):
        def descendants(self):
            return [
                FakeControl(FakeRect(83, 100, 339, 180), "左侧会话", "ListItem", "mmui::ChatSessionCell"),
                FakeControl(FakeRect(341, 103, 791, 366), "右侧卡片", "ListItem", "mmui::ChatBubbleReferItemView"),
            ]

    client = WxautoArticleRpaClient(wx=FakeArticleWx())
    window = FakeMainWindow(FakeRect(0, 0, 800, 1000), "", "Window", "mmui::MainWindow")

    row = client._find_first_history_row(window)

    assert row is not None
    assert row.window_text() == "右侧卡片"


def test_default_route_labels_include_minrong_platform() -> None:
    client = WxautoArticleRpaClient(wx=FakeArticleWx())

    assert "闽融平台" in client.route_entry_labels


def test_wxauto_article_client_falls_back_when_cache_get_raises() -> None:
    wx = FakeArticleWx()
    repo = RaisingRouteCacheRepo(route=FakeRoute())
    client = WxautoArticleRpaClient(
        wx=wx,
        route_cache_repo=repo,
        link_extract_methods=("visible_text",),
    )

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert len(repo.failures) == 1
    assert repo.failures[0]["error_code"] == "ROUTE_CACHE_GET_FAILED"
    assert repo.successes[-1]["route_type"] == "visible_text"


def test_wxauto_article_client_disables_route_cache_end_to_end() -> None:
    wx = FakeArticleWx()
    repo = FakeRouteCacheRepo(route=FakeRoute())
    client = WxautoArticleRpaClient(
        wx=wx,
        route_cache_repo=repo,
        route_cache_enabled=False,
        link_extract_methods=("visible_text",),
    )

    client.open_public_account("行业观察")
    links = client.copy_latest_article_links(max_articles=1)

    assert links == ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]
    assert repo.successes == []
    assert repo.failures == []


def test_wxauto_group_client_prefers_wxauto4_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeWeChat4:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

    def broken_legacy_wechat():
        raise AssertionError("legacy wxauto should not be used for WeChat 4.x")

    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=FakeWeChat4))
    monkeypatch.setitem(sys.modules, "wxauto", SimpleNamespace(WeChat=broken_legacy_wechat))

    client = WxautoGroupRpaClient()

    assert isinstance(client.wx, FakeWeChat4)
    assert calls == [{"ads": False}]


def test_wxauto_group_client_retries_wxauto4_after_preparing_chat_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    prepare_calls = 0

    class FakeWeChat4:
        def __init__(self, **kwargs) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise AttributeError("'NoneType' object has no attribute 'GroupControl'")

    def prepare_chat_page() -> None:
        nonlocal prepare_calls
        prepare_calls += 1

    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=FakeWeChat4))
    monkeypatch.setitem(sys.modules, "wxauto", None)
    monkeypatch.setattr(
        WxautoGroupRpaClient,
        "_prepare_wechat_chat_page",
        staticmethod(prepare_chat_page),
        raising=False,
    )

    client = WxautoGroupRpaClient()

    assert isinstance(client.wx, FakeWeChat4)
    assert attempts == 2
    assert prepare_calls == 1


def test_wxauto_group_client_uses_bounded_wxauto4_initialization_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    prepare_calls = 0

    class FakeWeChat4:
        def __init__(self, **kwargs) -> None:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise AttributeError("'NoneType' object has no attribute 'GroupControl'")

    def prepare_chat_page() -> None:
        nonlocal prepare_calls
        prepare_calls += 1

    monkeypatch.setitem(sys.modules, "wxauto4", SimpleNamespace(WeChat=FakeWeChat4))
    monkeypatch.setitem(sys.modules, "wxauto", None)
    monkeypatch.setattr(
        WxautoGroupRpaClient,
        "_prepare_wechat_chat_page",
        staticmethod(prepare_chat_page),
        raising=False,
    )
    monkeypatch.setattr("app.rpa.wxauto_client.time.sleep", lambda seconds: None)

    client = WxautoGroupRpaClient()

    assert isinstance(client.wx, FakeWeChat4)
    assert attempts == 3
    assert prepare_calls == 2


def test_wxauto_group_client_wraps_adapter_initialization_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_wechat():
        raise RuntimeError("SetWindowPos invalid window handle")

    monkeypatch.setitem(sys.modules, "wxauto4", None)
    monkeypatch.setitem(sys.modules, "wxauto", SimpleNamespace(WeChat=broken_wechat))

    with pytest.raises(WxautoNotAvailableError, match="wxauto adapter initialization failed") as exc_info:
        WxautoGroupRpaClient()

    assert "SetWindowPos invalid window handle" in str(exc_info.value)
