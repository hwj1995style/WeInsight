from __future__ import annotations

import importlib
import re
import time
from datetime import date, datetime
from typing import Any

from app.rpa.article_link_extraction import (
    extract_article_detail_urls,
    read_article_url_from_clipboard_copy,
)
from app.rpa.interfaces import VisibleMessage


_CHAT_WITH_ATTEMPTS = 6
_CHAT_WITH_RETRY_DELAY_SECONDS = 1.0
_PUBLIC_ACCOUNT_WINDOW_READY_TIMEOUT_SECONDS = 3.0
_PUBLIC_ACCOUNT_WINDOW_READY_POLL_SECONDS = 0.2
_WECHAT_INIT_ATTEMPTS = 3
_WECHAT_INIT_RETRY_DELAY_SECONDS = 1.0
_WECHAT_BROWSER_PROCESS_NAMES = {"wechat.exe", "wechatappex.exe", "weixin.exe"}


class WxautoNotAvailableError(RuntimeError):
    pass


class NoSameDayArticleAvailable(RuntimeError):
    pass


class WxautoGroupRpaClient:
    def __init__(self, wx: Any | None = None, current_group_name: str | None = None) -> None:
        self.wx = wx if wx is not None else self._create_wechat()
        self.current_group_name = current_group_name

    def open_group(self, group_name: str) -> None:
        if not hasattr(self.wx, "ChatWith"):
            raise AttributeError("wxauto WeChat object does not expose ChatWith(group_name).")
        _chat_with_retry(self.wx, group_name)
        self.current_group_name = group_name

    def read_visible_messages(self) -> list[VisibleMessage]:
        if not hasattr(self.wx, "GetAllMessage"):
            raise AttributeError("wxauto WeChat object does not expose GetAllMessage().")
        raw_messages = self.wx.GetAllMessage()
        return [self._normalize_message(item) for item in raw_messages]

    def scroll_up_messages(self, pages: int = 1) -> None:
        scroll = getattr(self.wx, "ScrollUp", None)
        if callable(scroll):
            for _ in range(pages):
                scroll()

    def _normalize_message(self, item: Any) -> VisibleMessage:
        group_name = self.current_group_name or ""
        if isinstance(item, dict):
            return VisibleMessage(
                group_name=group_name,
                sender_name=str(item.get("sender") or item.get("sender_name") or ""),
                msg_time_display=str(item.get("time") or item.get("msg_time_display") or ""),
                msg_content=str(item.get("content") or item.get("msg_content") or ""),
                msg_type=str(item.get("type") or item.get("msg_type") or "text"),
            )
        if isinstance(item, (tuple, list)):
            sender = "" if len(item) < 1 else str(item[0])
            content = "" if len(item) < 2 else str(item[1])
            time_display = "" if len(item) < 3 else str(item[2])
            msg_type = "text" if len(item) < 4 else str(item[3])
            return VisibleMessage(
                group_name=group_name,
                sender_name=sender,
                msg_time_display=time_display,
                msg_content=content,
                msg_type=msg_type,
            )
        return VisibleMessage(
            group_name=group_name,
            sender_name=str(getattr(item, "sender", getattr(item, "sender_name", ""))),
            msg_time_display=str(getattr(item, "time", getattr(item, "msg_time_display", ""))),
            msg_content=str(getattr(item, "content", getattr(item, "msg_content", item))),
            msg_type=str(getattr(item, "type", getattr(item, "msg_type", "text"))),
        )

    @staticmethod
    def _create_wechat() -> Any:
        import_errors: list[str] = []
        for module_name in ("wxauto4", "wxauto"):
            try:
                module = importlib.import_module(module_name)
                WeChat = getattr(module, "WeChat")
            except (ImportError, AttributeError) as exc:
                import_errors.append(f"{module_name}: {exc}")
                continue

            kwargs = {"ads": False} if module_name == "wxauto4" else {}
            try:
                if module_name == "wxauto4":
                    return WxautoGroupRpaClient._create_wechat4_with_retry(WeChat, kwargs)
                return WeChat(**kwargs)
            except Exception as exc:
                raise WxautoNotAvailableError(
                    f"{module_name} adapter initialization failed. "
                    "For WeChat PC 4.x, verify the RPA adapter supports the exact client version "
                    f"before running real collection. cause={exc}"
                ) from exc

        details = "; ".join(import_errors) if import_errors else "no adapter module was tried"
        raise WxautoNotAvailableError(
            "wxauto4 or wxauto is not installed. Install a compatible WeChat RPA adapter "
            f"before running real RPA POC. details={details}"
        )

    @staticmethod
    def _create_wechat4_with_retry(WeChat: Any, kwargs: dict[str, object]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(_WECHAT_INIT_ATTEMPTS):
            try:
                return WeChat(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt == _WECHAT_INIT_ATTEMPTS - 1:
                    break
                try:
                    WxautoGroupRpaClient._prepare_wechat_chat_page()
                except Exception as prepare_exc:
                    last_exc = prepare_exc
                time.sleep(_WECHAT_INIT_RETRY_DELAY_SECONDS)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("wxauto4 adapter initialization failed")

    @staticmethod
    def _prepare_wechat_chat_page() -> None:
        from pywinauto import Desktop

        win = Desktop(backend="uia").window(class_name="mmui::MainWindow")
        win.set_focus()
        for item in win.descendants(control_type="Button"):
            if item.element_info.class_name == "mmui::XTabBarItem":
                _activate_control(item)
                time.sleep(1)
                return


class WxautoArticleRpaClient:
    def __init__(
        self,
        wx: Any | None = None,
        current_account_name: str | None = None,
        route_cache_repo: Any | None = None,
        route_cache_enabled: bool = True,
        route_probe_enabled: bool = True,
        route_probe_failure_threshold: int = 3,
        route_entry_labels: tuple[str, ...] = (
            "历史消息",
            "全部消息",
            "往期文章",
            "文章",
            "资讯",
            "蛋价资讯",
            "闽融平台",
        ),
        link_extract_methods: tuple[str, ...] = ("copy_link_menu", "uia_value", "visible_text"),
        close_browser_after_extract: bool = False,
        open_account_search_fallback_enabled: bool = False,
    ) -> None:
        self.wx = wx if wx is not None else WxautoGroupRpaClient._create_wechat()
        self.current_account_name = current_account_name
        self.route_cache_repo = route_cache_repo
        self.route_cache_enabled = route_cache_enabled
        self.route_probe_enabled = route_probe_enabled
        self.route_probe_failure_threshold = route_probe_failure_threshold
        self.route_entry_labels = route_entry_labels
        self.link_extract_methods = link_extract_methods
        self.close_browser_after_extract = close_browser_after_extract
        self.open_account_search_fallback_enabled = open_account_search_fallback_enabled

    def open_public_account(self, account_name: str) -> None:
        if not hasattr(self.wx, "ChatWith"):
            raise AttributeError("wxauto WeChat object does not expose ChatWith(account_name).")
        _chat_with_retry(self.wx, account_name)
        if self.open_account_search_fallback_enabled and not self._wait_for_public_account_window(
            account_name
        ):
            if not self._open_public_account_from_main_search(
                account_name
            ) or not self._wait_for_public_account_window(account_name):
                raise RuntimeError("public account window not found")
        self.current_account_name = account_name

    def copy_latest_article_links(self, max_articles: int) -> list[str]:
        if max_articles <= 0:
            return []

        cleanup_browser = False
        try:
            cached_route = self._get_cached_route()
            if cached_route is not None:
                cleanup_browser = _route_uses_browser(cached_route)
                try:
                    if cleanup_browser:
                        self._prepare_browser_route_for_current_account()
                    links = self._copy_links_by_route(cached_route, max_articles)
                except NoSameDayArticleAvailable:
                    return []
                except Exception as exc:
                    self._mark_route_failure("CACHED_ROUTE_FAILED", exc)
                else:
                    if links:
                        self._mark_route_success(
                            cached_route.route_type,
                            cached_route.link_extract_type,
                            cached_route.entry_label,
                            cached_route.entry_index,
                        )
                        return links
                    self._mark_route_failure("CACHED_ROUTE_EMPTY", None)

            if not self.route_probe_enabled:
                return []

            history_candidates_opened = False
            browser_route_ready = False
            last_exc: Exception | None = None
            for method in self.link_extract_methods:
                uses_browser_route = method in {"copy_link_menu", "uia_value"}
                if uses_browser_route:
                    cleanup_browser = True
                if uses_browser_route and not history_candidates_opened:
                    try:
                        self._prepare_browser_route_for_current_account()
                    except NoSameDayArticleAvailable:
                        return []
                    except Exception as exc:
                        last_exc = exc
                        history_candidates_opened = True
                        browser_route_ready = False
                    else:
                        history_candidates_opened = True
                        browser_route_ready = True
                if uses_browser_route and not browser_route_ready:
                    continue
                try:
                    links = self._copy_links_by_method(method, max_articles)
                except Exception as exc:
                    last_exc = exc
                    continue
                if links:
                    route_type = "visible_text" if method == "visible_text" else "probe"
                    self._mark_route_success(route_type, method, None, None)
                    return links

            if last_exc is not None:
                raise last_exc
            return []
        finally:
            if cleanup_browser and self.close_browser_after_extract:
                self._close_large_browser_windows()
                self._close_current_account_window()

    def _prepare_browser_route_for_current_account(self) -> None:
        if self.close_browser_after_extract:
            self._close_large_browser_windows()
        self._open_history_entry_candidates()
        if not self._browser_detail_window_visible(target_date=date.today()):
            if self._browser_detail_window_visible(target_date=None):
                raise NoSameDayArticleAvailable("browser detail publish date is not today")
            raise RuntimeError("browser detail window not found")

    def _get_cached_route(self) -> Any | None:
        if not self.route_cache_enabled or self.route_cache_repo is None:
            return None
        account_name = self.current_account_name
        if not account_name:
            return None
        getter = getattr(self.route_cache_repo, "get_active_route", None)
        if not callable(getter):
            return None
        try:
            return getter(account_name)
        except Exception as exc:
            self._mark_route_failure("ROUTE_CACHE_GET_FAILED", exc)
            return None

    def _copy_links_by_route(self, route: Any, max_articles: int) -> list[str]:
        method = str(getattr(route, "link_extract_type", "") or getattr(route, "route_type", ""))
        return self._copy_links_by_method(method, max_articles)

    def _copy_links_by_method(self, method: str, max_articles: int) -> list[str]:
        if method == "visible_text":
            return self._copy_visible_text_article_links(max_articles)
        if method == "copy_link_menu":
            return self._copy_link_menu_article_links(max_articles)
        if method == "uia_value":
            return self._uia_value_article_links(max_articles)
        return []

    def _copy_visible_text_article_links(self, max_articles: int) -> list[str]:
        if not hasattr(self.wx, "GetAllMessage"):
            raise AttributeError("wxauto WeChat object does not expose GetAllMessage().")
        return extract_article_detail_urls(
            (value for item in self.wx.GetAllMessage() for value in _iter_text_values(item)),
            max_articles=max_articles,
        )

    def _copy_link_menu_article_links(self, max_articles: int) -> list[str]:
        if max_articles <= 0:
            return []

        pyperclip = importlib.import_module("pyperclip")
        url = read_article_url_from_clipboard_copy(
            self._click_copy_link_menu_item,
            paste=pyperclip.paste,
            copy=pyperclip.copy,
        )
        return [] if url is None else [url]

    def _uia_value_article_links(self, max_articles: int) -> list[str]:
        if max_articles <= 0:
            return []

        Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        values: list[str] = []
        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            if not _is_large_browser_window(window):
                continue
            for control in _safe_descendants(window, limit=3000):
                try:
                    values.append(control.iface_value.CurrentValue or "")
                except Exception:
                    continue
        return extract_article_detail_urls(values, max_articles=max_articles)

    def _click_copy_link_menu_item(self) -> None:
        Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        desktop = Desktop(backend="uia")
        browser_window = self._find_large_browser_window(desktop)
        if browser_window is None:
            raise RuntimeError("browser detail window not found")

        if not self._click_browser_app_menu_button(browser_window):
            rect = _safe_rectangle(browser_window)
            if rect is None:
                raise RuntimeError("browser detail window not found")
            _activate_control(browser_window, coords=(max(rect.width() - 36, 1), 48))
            time.sleep(0.3)

        menu_item = self._find_menu_item(desktop, "复制链接")
        if menu_item is None:
            raise RuntimeError("copy link menu item not found")
        _activate_control(menu_item)

    def _open_history_entry_candidates(self) -> None:
        Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        desktop = Desktop(backend="uia")
        account_window = self._find_account_container(desktop)
        browser_window = self._find_large_browser_window(desktop)
        if account_window is None and browser_window is None:
            raise RuntimeError("current account window not found")

        if account_window is not None:
            clicked_entry = self._click_route_entry_label(account_window)
            if not clicked_entry:
                first_row = self._find_first_history_row(account_window)
                if first_row is not None:
                    _activate_control(
                        first_row,
                        coords=_history_row_click_coords(first_row),
                        prefer_physical=_history_row_prefers_physical_click(first_row),
                    )
                    time.sleep(0.8)
                    if self._wait_for_browser_detail(target_date=date.today()):
                        return
                    if self._browser_detail_window_visible(target_date=None):
                        raise NoSameDayArticleAvailable("browser detail publish date is not today")
                    if not self._large_browser_window_visible():
                        if not self._click_account_info_entry_if_browser_missing(account_window):
                            raise RuntimeError("history entry route not found")
                else:
                    if not self._click_account_info_entry(account_window):
                        raise RuntimeError("history entry route not found")
                    time.sleep(0.5)
            else:
                time.sleep(0.5)
        if self._browser_detail_window_visible(target_date=date.today()):
            return
        if self._browser_detail_window_visible(target_date=None):
            raise NoSameDayArticleAvailable("browser detail publish date is not today")

        browser_window, first_row = self._wait_for_history_row(desktop, account_window)
        if first_row is None:
            raise RuntimeError("history list row not found")
        click_coords = (
            _uncovered_click_coords(
                first_row,
                [_safe_rectangle(account_window), *_wechat_overlay_rects(desktop, browser_window)],
            )
            if browser_window is not None
            else _history_row_click_coords(first_row)
        )
        _activate_control(first_row, coords=click_coords, prefer_physical=browser_window is not None)
        time.sleep(0.8)

        if self._wait_for_browser_detail(target_date=date.today()):
            return
        if self._browser_detail_window_visible(target_date=None):
            raise NoSameDayArticleAvailable("browser detail publish date is not today")
        raise RuntimeError("browser detail window not found")

    def _wait_for_history_row(
        self,
        desktop: Any,
        account_window: Any | None,
        timeout_seconds: float = 8.0,
    ) -> tuple[Any | None, Any | None]:
        deadline = time.time() + timeout_seconds
        browser_window = self._find_large_browser_window(desktop)
        while time.time() < deadline:
            browser_window = self._find_large_browser_window(desktop)
            history_container = browser_window if browser_window is not None else account_window
            if history_container is not None:
                if browser_window is not None:
                    _focus_window(browser_window)
                if browser_window is not None:
                    first_row = self._find_first_history_row(
                        history_container,
                        require_target_date=True,
                        top_only=True,
                    )
                    if first_row is None:
                        first_visible_row = self._find_first_history_row(
                            history_container,
                            require_target_date=False,
                            top_only=True,
                        )
                        if first_visible_row is not None:
                            return browser_window, first_visible_row
                else:
                    first_row = self._find_first_history_row(
                        history_container,
                        require_target_date=False,
                    )
                if first_row is not None:
                    return browser_window, first_row
            time.sleep(0.3)
        return browser_window, None

    def _wait_for_browser_detail(
        self,
        timeout_seconds: float = 5.0,
        target_date: date | None = None,
    ) -> bool:
        detail_target_date = target_date or date.today()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._browser_detail_window_visible(target_date=detail_target_date):
                return True
            time.sleep(0.2)
        return False

    def _browser_detail_window_visible(self, target_date: date | None = None) -> bool:
        try:
            Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        except Exception:
            return False

        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            if not _is_large_browser_window(window):
                continue
            if not _browser_current_article_urls(window, max_articles=1):
                continue
            if target_date is None:
                return True
            if _browser_visible_publish_date_matches(window, target_date):
                return True
        return False

    def _visible_text_links_available(self) -> bool:
        try:
            return bool(self._copy_visible_text_article_links(1))
        except Exception:
            return False

    def _find_large_browser_window(self, desktop: Any) -> Any | None:
        for window in desktop.windows():
            if _is_large_browser_window(window):
                return window
        return None

    def _large_browser_window_visible(self) -> bool:
        try:
            Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        except Exception:
            return False
        return self._find_large_browser_window(Desktop(backend="uia")) is not None

    def _public_account_window_visible(self, account_name: str) -> bool:
        expected_name = _normalize_match_text(account_name)
        if not expected_name:
            return False
        try:
            Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        except Exception:
            return False
        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            class_name = _safe_class_name(window)
            if class_name == "mmui::ChatSingleWindow":
                if _normalize_match_text(_safe_text(window)) == expected_name:
                    return True
                continue
            if class_name != "mmui::MainWindow":
                continue
            if _main_chat_title_matches(window, expected_name):
                return True
        return False

    def _open_public_account_from_main_search(self, account_name: str) -> bool:
        try:
            pyperclip = importlib.import_module("pyperclip")
            pywinauto = importlib.import_module("pywinauto")
            keyboard = importlib.import_module("pywinauto.keyboard")
        except Exception:
            return False

        desktop = pywinauto.Desktop(backend="uia")
        main_window = _find_wechat_main_window(desktop)
        if main_window is None:
            return False
        search_edit = _find_main_search_edit(main_window)
        if search_edit is None:
            return False

        previous_clipboard = ""
        try:
            previous_clipboard = pyperclip.paste()
        except Exception:
            previous_clipboard = ""

        try:
            _focus_window(main_window)
            _activate_control(search_edit, prefer_physical=True)
            time.sleep(0.2)
            pyperclip.copy(account_name)
            keyboard.send_keys("^a{BACKSPACE}^v")
            result = _wait_for_main_search_result(main_window, account_name)
            if result is None:
                return False
            _activate_control(result, prefer_physical=True)
            time.sleep(1.0)
            return True
        finally:
            try:
                pyperclip.copy(previous_clipboard)
            except Exception:
                pass

    def _wait_for_public_account_window(self, account_name: str) -> bool:
        deadline = time.monotonic() + _PUBLIC_ACCOUNT_WINDOW_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._public_account_window_visible(account_name):
                return True
            time.sleep(_PUBLIC_ACCOUNT_WINDOW_READY_POLL_SECONDS)
        return self._public_account_window_visible(account_name)

    def _click_account_info_entry_if_browser_missing(self, account_window: Any) -> bool:
        if self._large_browser_window_visible():
            return False
        if not self._click_account_info_entry(account_window):
            return False
        time.sleep(0.5)
        return True

    def _close_large_browser_windows(self) -> None:
        try:
            Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        except Exception:
            return
        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            if not _is_large_browser_window(window):
                continue
            _close_window(window)

    def _close_current_account_window(self) -> None:
        try:
            Desktop = getattr(importlib.import_module("pywinauto"), "Desktop")
        except Exception:
            return
        try:
            account_window = self._find_account_window(Desktop(backend="uia"))
        except Exception:
            return
        if account_window is None:
            return
        _close_window(account_window)

    def _click_browser_app_menu_button(self, browser_window: Any) -> bool:
        for control in _safe_descendants(browser_window, limit=200):
            name = _safe_text(control)
            automation_id = _safe_automation_id(control)
            control_type = _safe_control_type(control)
            if automation_id == "AppMenuButton" or (
                control_type == "Button" and name == "更多"
            ):
                _activate_control(control)
                time.sleep(0.3)
                return True
        return False

    def _find_menu_item(self, desktop: Any, text: str) -> Any | None:
        browser_window = self._find_large_browser_window(desktop)
        browser_rect = _safe_rectangle(browser_window) if browser_window is not None else None
        candidate_windows = self._menu_search_windows(desktop, browser_window, browser_rect)
        for window in candidate_windows:
            for control in _safe_descendants(window, limit=500):
                if _safe_text(control) != text:
                    continue
                if _safe_control_type(control) not in {"MenuItem", "Button"}:
                    continue
                if not _has_positive_visible_rect(control):
                    continue
                return control
        return None

    def _find_account_window(self, desktop: Any) -> Any | None:
        expected_name = _normalize_match_text(self.current_account_name or "")
        candidates: list[Any] = []
        for window in desktop.windows():
            if _safe_class_name(window) != "mmui::ChatSingleWindow":
                continue
            if expected_name and _normalize_match_text(_safe_text(window)) == expected_name:
                return window
            candidates.append(window)
        if expected_name:
            return None
        return candidates[0] if len(candidates) == 1 else None

    def _find_account_container(self, desktop: Any) -> Any | None:
        account_window = self._find_account_window(desktop)
        if account_window is not None:
            return account_window
        return None

    def _menu_search_windows(
        self,
        desktop: Any,
        browser_window: Any | None,
        browser_rect: Any | None,
    ) -> list[Any]:
        windows = list(desktop.windows())
        prioritized: list[Any] = []
        if browser_window is not None:
            prioritized.append(browser_window)
        for window in windows:
            if window is browser_window:
                continue
            if _is_menu_context_window(window, browser_rect):
                prioritized.append(window)
        return prioritized

    def _click_route_entry_label(self, account_window: Any) -> bool:
        labels = set(self.route_entry_labels)
        for control in _safe_descendants(account_window, limit=1500):
            if _safe_text(control) not in labels:
                continue
            _activate_control(control, prefer_physical=_safe_class_name(control) == "mmui::BizMenuButton")
            return True
        return False

    def _click_bottom_menu_fallback(self, account_window: Any) -> bool:
        rect = _safe_rectangle(account_window)
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return False
        _activate_control(account_window, coords=(rect.width() // 2, max(rect.height() - 48, 1)))
        return True

    def _click_account_info_entry(self, account_window: Any) -> bool:
        rect = _safe_rectangle(account_window)
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return False
        for control in _safe_descendants(account_window, limit=500):
            control_rect = _safe_rectangle(control)
            if control_rect is None:
                continue
            if control_rect.top > rect.top + 140:
                continue
            if control_rect.left < rect.right - 180:
                continue
            if _safe_control_type(control) != "Button":
                continue
            if _safe_text(control) in {"聊天信息", "账号信息", "公众号信息"}:
                _activate_control(control)
                return True
        _activate_control(account_window, coords=(max(rect.width() - 40, 1), 68))
        return True

    def _find_first_history_row(
        self,
        account_window: Any,
        *,
        target_date: date | None = None,
        require_target_date: bool = False,
        top_only: bool = False,
    ) -> Any | None:
        rect = _safe_rectangle(account_window)
        if rect is None:
            return None
        candidates: list[tuple[int, int, int, int, int, Any]] = []
        row_target_date = target_date or date.today()
        window_class_name = _safe_class_name(account_window)
        top_guard = _history_row_top_guard(window_class_name, rect)
        left_content_guard = (
            rect.left + max(rect.width() // 3, 300)
            if window_class_name == "mmui::MainWindow"
            else rect.left
        )
        visible_controls: list[tuple[Any, Any]] = []
        for control in _safe_descendants(account_window, limit=2000):
            control_rect = _safe_rectangle(control)
            if control_rect is None:
                continue
            if control_rect.height() <= 0 or control_rect.width() <= 0:
                continue
            if control_rect.right <= rect.left or control_rect.left >= rect.right:
                continue
            if control_rect.right <= left_content_guard:
                continue
            if control_rect.bottom <= rect.top or control_rect.top >= rect.bottom:
                continue
            if control_rect.top < rect.top:
                continue
            visible_controls.append((control_rect, control))

        for control_rect, control in visible_controls:
            class_name = _safe_class_name(control)
            is_article_title = _is_history_article_title_class(class_name)
            min_height = 14 if is_article_title else 24
            min_width = 24 if is_article_title else 120
            if control_rect.height() < min_height or control_rect.width() < min_width:
                continue
            is_top_article_card = (
                class_name in {"mmui::ChatAppReaderItemView", "mmui::ChatBubbleReferItemView"}
                and control_rect.height() >= 80
            )
            if control_rect.top <= top_guard and not is_top_article_card:
                continue
            if class_name == "mmui::BizMenuButton":
                continue
            if _safe_control_type(control) not in {"ListItem", "DataItem", "Button", "Text", "Static", ""}:
                continue
            date_priority = _history_row_date_priority(control, row_target_date)
            if date_priority > 1:
                date_priority = _nearby_history_target_date_priority(
                    control,
                    control_rect,
                    visible_controls,
                    row_target_date,
                )
            candidates.append((
                date_priority,
                _history_row_quote_priority(control),
                _history_row_priority(control),
                control_rect.top,
                control_rect.left,
                control,
            ))
        if not candidates:
            return None
        if top_only:
            candidates.sort(key=lambda item: (item[3], item[2], item[4]))
            first_candidate = candidates[0]
            if require_target_date and first_candidate[0] > 1:
                return None
            return first_candidate[5]
        if require_target_date:
            candidates = [candidate for candidate in candidates if candidate[0] <= 1]
            if not candidates:
                return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
        return candidates[0][5]

    def _mark_route_success(
        self,
        route_type: str,
        link_extract_type: str,
        entry_label: str | None,
        entry_index: int | None,
    ) -> None:
        if not self.route_cache_enabled or self.route_cache_repo is None:
            return
        upsert_success = getattr(self.route_cache_repo, "upsert_success", None)
        if not callable(upsert_success) or not self.current_account_name:
            return
        try:
            upsert_success(
                account_name=self.current_account_name,
                route_type=route_type,
                link_extract_type=link_extract_type,
                entry_label=entry_label,
                entry_index=entry_index,
                success_time=datetime.now(),
            )
        except Exception:
            return

    def _mark_route_failure(self, error_code: str, exc: Exception | None) -> None:
        if not self.route_cache_enabled or self.route_cache_repo is None:
            return
        mark_failure = getattr(self.route_cache_repo, "mark_failure", None)
        if not callable(mark_failure) or not self.current_account_name:
            return
        error_msg = "" if exc is None else _safe_probe_message(exc)
        try:
            mark_failure(
                account_name=self.current_account_name,
                error_code=error_code,
                error_msg=error_msg,
                failure_time=datetime.now(),
                failure_threshold=self.route_probe_failure_threshold,
            )
        except Exception:
            return

    def probe_account(self, account_name: str) -> dict[str, object]:
        try:
            self.open_public_account(account_name)
        except Exception as exc:
            return {
                "status": "failed",
                "account_found": 0,
                "link_count": 0,
                "message": _safe_probe_message(exc),
            }

        try:
            links = self.copy_latest_article_links(max_articles=3)
        except Exception as exc:
            return {
                "status": "failed",
                "account_found": 1,
                "link_count": 0,
                "message": _safe_probe_message(exc),
            }

        return {
            "status": "ok",
            "account_found": 1,
            "link_count": len(links),
            "message": "ready",
        }


def _iter_text_values(item: Any):
    if isinstance(item, dict):
        for key in ("content", "msg_content", "url", "link", "href", "title"):
            value = item.get(key)
            if value is not None:
                yield str(value)
        return

    if isinstance(item, (tuple, list)):
        for value in item:
            if value is not None:
                yield str(value)
        return

    for attr in ("content", "msg_content", "url", "link", "href", "title"):
        value = getattr(item, attr, None)
        if value is not None:
            yield str(value)


def _route_uses_browser(route: Any) -> bool:
    method = str(getattr(route, "link_extract_type", "") or getattr(route, "route_type", ""))
    return method in {"copy_link_menu", "uia_value"}


def _history_row_priority(control: Any) -> int:
    class_name = _safe_class_name(control)
    if class_name in {"mmui::ChatAppReaderItemView", "mmui::ChatBubbleReferItemView"}:
        return 0
    if class_name == "weui_media_title":
        return 0
    if class_name == "mmui::ChatItemView":
        return 2
    return 1


def _history_row_quote_priority(control: Any) -> int:
    text = _normalize_match_text(_history_row_candidate_text(control))
    if not text:
        return 5
    compact_text = re.sub(r"\s+", "", text)
    if any(word in compact_text for word in ("广告位", "拉稀", "流感", "减产", "防治", "方案")):
        return 9
    if any(word in compact_text for word in ("鸡蛋报价", "蛋价", "鸡蛋价格", "今日价格", "报价")):
        return 0
    return 5


def _history_row_candidate_text(control: Any) -> str:
    parts = [_safe_text(control)]
    for child in _safe_descendants(control, limit=30):
        text = _safe_text(child)
        if text:
            parts.append(text)
    return " ".join(part for part in parts if part)


def _history_row_top_guard(window_class_name: str, rect: Any) -> int:
    if window_class_name.startswith("mmui::"):
        return rect.top + 120
    if window_class_name.startswith("Chrome_WidgetWin_"):
        return rect.top + min(max(rect.height() // 4, 220), 300)
    return rect.top + max(rect.height() // 3, 120)


def _is_history_article_title_class(class_name: str) -> bool:
    return class_name in {"article__item__title", "weui_media_title"} or "article" in class_name


def _history_row_date_priority(control: Any, target_date: date) -> int:
    text = _normalize_match_text(_safe_text(control))
    if not text:
        return 2
    compact_text = re.sub(r"\s+", "", text)
    markers = {
        f"{target_date.year}年{target_date.month}月{target_date.day}日",
        f"{target_date.year}年{target_date.month:02d}月{target_date.day:02d}日",
        f"{target_date.month}月{target_date.day}日",
        f"{target_date.month:02d}月{target_date.day:02d}日",
        target_date.isoformat(),
        target_date.strftime("%Y/%m/%d"),
    }
    if any(marker in compact_text for marker in markers):
        return 0

    class_name = _safe_class_name(control)
    if _is_history_article_title_class(class_name) and compact_text in {str(target_date.day), f"{target_date.day:02d}"}:
        return 1
    return 2


def _nearby_history_target_date_priority(
    control: Any,
    control_rect: Any,
    visible_controls: list[tuple[Any, Any]],
    target_date: date,
) -> int:
    if not _is_history_article_title_class(_safe_class_name(control)):
        return 2

    for other_rect, other in visible_controls:
        if other is control:
            continue
        if _history_row_date_priority(other, target_date) != 0:
            continue
        if _is_nearby_history_row_text(control_rect, other_rect):
            return 0
    return 2


def _is_nearby_history_row_text(control_rect: Any, other_rect: Any) -> bool:
    if other_rect.top < control_rect.top - 8:
        return False
    if other_rect.top > control_rect.bottom + 96:
        return False
    horizontal_overlap = min(control_rect.right, other_rect.right) - max(control_rect.left, other_rect.left)
    if horizontal_overlap > 0:
        return True
    return control_rect.left - 40 <= other_rect.left <= control_rect.right + 40


def _find_wechat_main_window(desktop: Any) -> Any | None:
    for window in desktop.windows():
        if _safe_class_name(window) == "mmui::MainWindow":
            return window
    return None


def _main_chat_title_matches(main_window: Any, expected_name: str) -> bool:
    rect = _safe_rectangle(main_window)
    for control in _safe_descendants(main_window, limit=800):
        control_rect = _safe_rectangle(control)
        if rect is not None and control_rect is not None:
            if control_rect.top > rect.top + 100:
                continue
            if control_rect.left < rect.left + 300:
                continue
        if expected_name in _normalize_match_text(_safe_text(control)):
            return True
    return False


def _find_main_search_edit(main_window: Any) -> Any | None:
    rect = _safe_rectangle(main_window)
    for control in _safe_descendants(main_window, limit=800):
        if _safe_class_name(control) != "mmui::XValidatorTextEdit":
            continue
        if _safe_control_type(control) != "Edit":
            continue
        control_rect = _safe_rectangle(control)
        if rect is not None and control_rect is not None:
            if control_rect.top > rect.top + 120:
                continue
            if control_rect.left < rect.left + 80 or control_rect.left > rect.left + 340:
                continue
        return control
    return None


def _wait_for_main_search_result(main_window: Any, account_name: str, timeout_seconds: float = 4.0) -> Any | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = _find_main_search_result(main_window, account_name)
        if result is not None:
            return result
        time.sleep(0.2)
    return None


def _find_main_search_result(main_window: Any, account_name: str) -> Any | None:
    expected_name = _normalize_match_text(account_name)
    rect = _safe_rectangle(main_window)
    candidates: list[tuple[int, int, Any]] = []
    for control in _safe_descendants(main_window, limit=3000):
        class_name = _safe_class_name(control)
        if class_name not in {"mmui::SearchContentCellView", "mmui::XTableCell"}:
            continue
        control_text = _normalize_match_text(_safe_text(control))
        if expected_name not in control_text:
            continue
        control_rect = _safe_rectangle(control)
        if control_rect is None:
            continue
        if rect is not None:
            if control_rect.top < rect.top + 80:
                continue
            if control_rect.left < rect.left + 80 or control_rect.left > rect.left + 520:
                continue
        priority = 0 if class_name == "mmui::SearchContentCellView" else 1
        candidates.append((priority, control_rect.top, control))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _browser_current_article_urls(window: Any, max_articles: int) -> list[str]:
    values: list[str] = []
    browser_rect = _safe_rectangle(window)
    for control in _safe_descendants(window, limit=500):
        value = _safe_control_value(control)
        if not value:
            continue
        if not _is_browser_current_url_control(control, browser_rect, value):
            continue
        values.append(value)
    return extract_article_detail_urls(values, max_articles=max_articles)


def _is_browser_current_url_control(control: Any, browser_rect: Any | None, value: str) -> bool:
    if "mp.weixin.qq.com" not in value:
        return False
    rect = _safe_rectangle(control)
    if rect is None or rect.width() < 120 or rect.height() <= 0:
        return False
    control_type = _safe_control_type(control)
    if browser_rect is not None:
        if rect.top < browser_rect.top or rect.top > browser_rect.top + 120:
            return False
        if rect.right <= browser_rect.left or rect.left >= browser_rect.right:
            return False
        if control_type == "Document" and rect.height() >= max(browser_rect.height() // 2, 200):
            return True
    if rect.height() > 100:
        return False
    return control_type in {"Edit", "ComboBox", "Text", "Document", "Pane", ""}


def _browser_visible_publish_date_matches(window: Any, target_date: date) -> bool:
    for control in _safe_descendants(window, limit=1500):
        if _text_contains_full_date(_safe_text(control), target_date):
            return True
        if _text_contains_full_date(_safe_control_value(control), target_date):
            return True
    return False


def _text_contains_full_date(value: str, target_date: date) -> bool:
    if not value:
        return False
    compact_text = re.sub(r"\s+", "", value)
    markers = {
        f"{target_date.year}年{target_date.month}月{target_date.day}日",
        f"{target_date.year}年{target_date.month:02d}月{target_date.day:02d}日",
        target_date.isoformat(),
        target_date.strftime("%Y/%m/%d"),
    }
    return any(marker in compact_text for marker in markers)


def _history_row_prefers_physical_click(control: Any) -> bool:
    return _safe_class_name(control) in {
        "mmui::ChatAppReaderItemView",
        "mmui::ChatBubbleReferItemView",
    }


def _history_row_click_coords(control: Any) -> tuple[int, int] | None:
    class_name = _safe_class_name(control)
    if class_name not in {"mmui::ChatAppReaderItemView", "mmui::ChatBubbleReferItemView"}:
        return None
    rect = _safe_rectangle(control)
    if rect is None or rect.width() <= 0 or rect.height() <= 0:
        return None
    x = max(1, min(rect.width() // 2, rect.width() - 1))
    if rect.height() >= 180:
        y = max(1, min(rect.height() // 5, rect.height() - 1))
    else:
        y = max(1, min(rect.height() // 2, rect.height() - 1))
    return (x, y)


def _safe_probe_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    message = re.sub(r"https?://\S+", "[redacted-url]", message)
    message = re.sub(r"mp\.weixin\.qq\.com/\S+", "[redacted-url]", message)
    message = re.sub(r"\s+", " ", message)
    return message[:160]


def _chat_with_retry(wx: Any, chat_name: str) -> None:
    last_exc: Exception | None = None
    for attempt in range(_CHAT_WITH_ATTEMPTS):
        try:
            wx.ChatWith(chat_name)
            return
        except Exception as exc:
            last_exc = exc
            if attempt == _CHAT_WITH_ATTEMPTS - 1:
                break
            time.sleep(_CHAT_WITH_RETRY_DELAY_SECONDS)

    if last_exc is not None:
        raise last_exc


def _focus_window(window: Any) -> None:
    set_focus = getattr(window, "set_focus", None)
    if not callable(set_focus):
        _focus_window_with_win32(window)
        return
    try:
        set_focus()
        time.sleep(0.2)
    except Exception:
        _focus_window_with_win32(window)


def _focus_window_with_win32(window: Any) -> None:
    handle = getattr(window, "handle", None)
    if callable(handle):
        try:
            handle = handle()
        except Exception:
            handle = None
    if not handle:
        return
    try:
        win32gui = importlib.import_module("win32gui")
        win32con = importlib.import_module("win32con")
        win32gui.ShowWindow(handle, getattr(win32con, "SW_RESTORE", 9))
        time.sleep(0.1)
        win32gui.SetForegroundWindow(handle)
        time.sleep(0.2)
    except Exception:
        return


def _close_window(window: Any) -> None:
    close = getattr(window, "close", None)
    if callable(close):
        try:
            close()
            time.sleep(0.2)
            return
        except Exception:
            pass

    handle = getattr(window, "handle", None)
    if callable(handle):
        try:
            handle = handle()
        except Exception:
            handle = None
    if not handle:
        return
    try:
        win32gui = importlib.import_module("win32gui")
        win32con = importlib.import_module("win32con")
        win32gui.PostMessage(handle, getattr(win32con, "WM_CLOSE", 0x0010), 0, 0)
        time.sleep(0.2)
    except Exception:
        return


def _uncovered_click_coords(control: Any, avoid_rects: Any | None) -> tuple[int, int] | None:
    rect = _safe_rectangle(control)
    avoid_rect_list = _as_rect_list(avoid_rects)
    if rect is None or not avoid_rect_list or rect.width() <= 0 or rect.height() <= 0:
        return None
    y = max(1, min(rect.height() // 2, rect.height() - 1))
    width = rect.width()
    candidates = [
        max(1, min(20, width - 1)),
        max(1, min(width // 4, width - 1)),
        max(1, min(width // 2, width - 1)),
        max(1, min(width - 20, width - 1)),
    ]
    for x in dict.fromkeys(candidates):
        absolute_x = rect.left + x
        absolute_y = rect.top + y
        if all(not _point_in_rect(absolute_x, absolute_y, avoid_rect) for avoid_rect in avoid_rect_list):
            return (x, y)
    return None


def _as_rect_list(value: Any | None) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "left") and hasattr(value, "right"):
        return [value]
    try:
        return [item for item in value if item is not None]
    except TypeError:
        return []


def _wechat_overlay_rects(desktop: Any, browser_window: Any | None) -> list[Any]:
    browser_rect = _safe_rectangle(browser_window) if browser_window is not None else None
    if browser_rect is None:
        return []
    rects: list[Any] = []
    for window in desktop.windows():
        class_name = _safe_class_name(window)
        if not class_name.startswith("mmui::"):
            continue
        rect = _safe_rectangle(window)
        if rect is None:
            continue
        if _rects_intersect(rect, browser_rect):
            rects.append(rect)
    return rects


def _rects_intersect(first: Any, second: Any) -> bool:
    return not (
        first.right <= second.left
        or first.left >= second.right
        or first.bottom <= second.top
        or first.top >= second.bottom
    )


def _point_in_rect(x: int, y: int, rect: Any) -> bool:
    return rect.left <= x <= rect.right and rect.top <= y <= rect.bottom


def _activate_control(
    control: Any,
    coords: tuple[int, int] | None = None,
    *,
    prefer_physical: bool = False,
) -> None:
    if coords is None and not prefer_physical:
        for method_name in ("invoke", "select"):
            method = getattr(control, method_name, None)
            if not callable(method):
                continue
            try:
                method()
                return
            except Exception:
                continue

        try:
            iface_invoke = getattr(control, "iface_invoke", None)
        except Exception:
            iface_invoke = None
        invoke = getattr(iface_invoke, "Invoke", None)
        if callable(invoke):
            try:
                invoke()
                return
            except Exception:
                pass

        try:
            iface_selection_item = getattr(control, "iface_selection_item", None)
        except Exception:
            iface_selection_item = None
        select = getattr(iface_selection_item, "Select", None)
        if callable(select):
            try:
                select()
                return
            except Exception:
                pass

    click_input = getattr(control, "click_input", None)
    if callable(click_input):
        try:
            if coords is None:
                click_input()
            else:
                click_input(coords=coords)
            return
        except Exception:
            _click_control_with_win32(control, coords=coords)
            return
    _click_control_with_win32(control, coords=coords)


def _click_control_with_win32(control: Any, coords: tuple[int, int] | None = None) -> None:
    rect = _safe_rectangle(control)
    if rect is None:
        raise AttributeError("control does not expose a supported activation method")
    if coords is None:
        x = rect.left + rect.width() // 2
        y = rect.top + rect.height() // 2
    else:
        x = rect.left + coords[0]
        y = rect.top + coords[1]
    win32api = importlib.import_module("win32api")
    win32con = importlib.import_module("win32con")
    win32api.SetCursorPos((x, y))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _safe_descendants(control: Any, limit: int) -> list[Any]:
    try:
        descendants = control.descendants()
    except Exception:
        return []
    try:
        return list(descendants[:limit])
    except Exception:
        items: list[Any] = []
        for index, item in enumerate(descendants):
            if index >= limit:
                break
            items.append(item)
        return items


def _safe_class_name(control: Any) -> str:
    getter = getattr(control, "class_name", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            return ""
    return str(getattr(getattr(control, "element_info", None), "class_name", "") or "")


def _safe_text(control: Any) -> str:
    for attr_name in ("window_text", "texts"):
        getter = getattr(control, attr_name, None)
        if not callable(getter):
            continue
        try:
            value = getter()
        except Exception:
            continue
        if isinstance(value, list):
            return str(value[0] or "") if value else ""
        return str(value or "")
    return str(getattr(getattr(control, "element_info", None), "name", "") or "")


def _safe_control_type(control: Any) -> str:
    for attr_name in ("friendly_class_name",):
        getter = getattr(control, attr_name, None)
        if not callable(getter):
            continue
        try:
            return str(getter() or "")
        except Exception:
            continue
    return str(getattr(getattr(control, "element_info", None), "control_type", "") or "")


def _safe_control_value(control: Any) -> str:
    try:
        iface_value = getattr(control, "iface_value", None)
    except Exception:
        return ""
    current_value = getattr(iface_value, "CurrentValue", None)
    if current_value is None:
        return ""
    return str(current_value or "")


def _safe_automation_id(control: Any) -> str:
    element_info = getattr(control, "element_info", None)
    return str(getattr(element_info, "automation_id", "") or "")


def _safe_rectangle(control: Any) -> Any | None:
    getter = getattr(control, "rectangle", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        return None


def _safe_process_name(window: Any) -> str:
    process_id = getattr(window, "process_id", None)
    if not callable(process_id):
        return ""
    try:
        pid = process_id()
    except Exception:
        return ""
    try:
        psutil = importlib.import_module("psutil")
        return str(psutil.Process(pid).name() or "")
    except Exception:
        return ""


def _is_large_browser_window(window: Any) -> bool:
    class_name = _safe_class_name(window)
    rect = _safe_rectangle(window)
    if not class_name.startswith("Chrome_WidgetWin"):
        return False
    if rect is None:
        return False
    process_name = _safe_process_name(window).lower()
    is_wechat_browser_process = process_name in _WECHAT_BROWSER_PROCESS_NAMES
    min_width = 600 if is_wechat_browser_process else 1000
    min_height = 600 if is_wechat_browser_process else 700
    if not (rect.width() > min_width and rect.height() > min_height and rect.left >= -100):
        return False
    if process_name:
        return is_wechat_browser_process
    return _normalize_match_text(_safe_text(window)).lower() != "codex"


def _has_positive_visible_rect(control: Any) -> bool:
    rect = _safe_rectangle(control)
    if rect is None:
        return False
    return (
        rect.width() > 0
        and rect.height() > 0
        and rect.right > 0
        and rect.bottom > 0
    )


def _is_menu_context_window(window: Any, browser_rect: Any | None) -> bool:
    rect = _safe_rectangle(window)
    control_type = _safe_control_type(window)
    class_name = _safe_class_name(window)
    if rect is not None and rect.width() > 0 and rect.height() > 0:
        near_browser = _is_rect_within_browser_context(rect, browser_rect)
        if (
            control_type in {"Menu", "Pane"}
            and class_name.startswith("Chrome_WidgetWin")
            and near_browser
        ):
            return True
        if control_type == "Menu" and near_browser:
            return True
        if near_browser and browser_rect is not None and (
            rect.width() < browser_rect.width() and rect.height() < browser_rect.height()
        ):
            return True

    if browser_rect is None:
        return False
    for control in _safe_descendants(window, limit=100):
        if _safe_control_type(control) not in {"MenuItem", "Button"}:
            continue
        control_rect = _safe_rectangle(control)
        if control_rect is None or control_rect.width() <= 0 or control_rect.height() <= 0:
            continue
        if _is_rect_within_browser_context(control_rect, browser_rect):
            return True
    return False


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_rect_within_browser_context(rect: Any, browser_rect: Any | None, padding: int = 80) -> bool:
    if browser_rect is None:
        return False
    return (
        rect.left >= browser_rect.left
        and rect.top >= browser_rect.top
        and rect.right <= browser_rect.right + padding
        and rect.bottom <= browser_rect.bottom + padding
    )
