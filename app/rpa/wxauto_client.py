from __future__ import annotations

import importlib
import time
from typing import Any

from app.rpa.interfaces import VisibleMessage


_CHAT_WITH_ATTEMPTS = 6
_CHAT_WITH_RETRY_DELAY_SECONDS = 1.0
_WECHAT_INIT_ATTEMPTS = 3
_WECHAT_INIT_RETRY_DELAY_SECONDS = 1.0


class WxautoNotAvailableError(RuntimeError):
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
        return [self._normalize_message(item) for item in self.wx.GetAllMessage()]

    def scroll_up_messages(self, pages: int = 1) -> None:
        scroll = getattr(self.wx, "ScrollUp", None)
        if callable(scroll):
            for _ in range(pages):
                scroll()

    def _normalize_message(self, item: Any) -> VisibleMessage:
        group_name = self.current_group_name or ""
        if isinstance(item, dict):
            return VisibleMessage(group_name, str(item.get("sender") or item.get("sender_name") or ""),
                str(item.get("time") or item.get("msg_time_display") or ""),
                str(item.get("content") or item.get("msg_content") or ""),
                str(item.get("type") or item.get("msg_type") or "text"))
        if isinstance(item, (tuple, list)):
            values = [str(value) for value in item]
            return VisibleMessage(group_name, values[0] if values else "", values[2] if len(values) > 2 else "",
                values[1] if len(values) > 1 else "", values[3] if len(values) > 3 else "text")
        return VisibleMessage(group_name,
            str(getattr(item, "sender", getattr(item, "sender_name", ""))),
            str(getattr(item, "time", getattr(item, "msg_time_display", ""))),
            str(getattr(item, "content", getattr(item, "msg_content", item))),
            str(getattr(item, "type", getattr(item, "msg_type", "text"))))

    @staticmethod
    def _create_wechat() -> Any:
        errors: list[str] = []
        for module_name in ("wxauto4", "wxauto"):
            try:
                wechat = getattr(importlib.import_module(module_name), "WeChat")
            except (ImportError, AttributeError) as exc:
                errors.append(f"{module_name}: {exc}")
                continue
            try:
                if module_name == "wxauto4":
                    return WxautoGroupRpaClient._create_wechat4_with_retry(wechat, {"ads": False})
                return wechat()
            except Exception as exc:
                raise WxautoNotAvailableError(
                    f"{module_name} adapter initialization failed. Verify the adapter supports the client version. cause={exc}"
                ) from exc
        raise WxautoNotAvailableError(
            "wxauto4 or wxauto is not installed. details=" + ("; ".join(errors) or "no adapter module was tried")
        )

    @staticmethod
    def _create_wechat4_with_retry(wechat: Any, kwargs: dict[str, object]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(_WECHAT_INIT_ATTEMPTS):
            try:
                return wechat(**kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < _WECHAT_INIT_ATTEMPTS - 1:
                    try:
                        WxautoGroupRpaClient._prepare_wechat_chat_page()
                    except Exception as prepare_exc:
                        last_exc = prepare_exc
                    time.sleep(_WECHAT_INIT_RETRY_DELAY_SECONDS)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _prepare_wechat_chat_page() -> None:
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(class_name="mmui::MainWindow")
        window.set_focus()
        for item in window.descendants(control_type="Button"):
            if item.element_info.class_name == "mmui::XTabBarItem":
                _activate_control(item)
                time.sleep(1)
                return


def _chat_with_retry(wx: Any, chat_name: str) -> None:
    last_exc: Exception | None = None
    for attempt in range(_CHAT_WITH_ATTEMPTS):
        try:
            wx.ChatWith(chat_name)
            return
        except Exception as exc:
            last_exc = exc
            if attempt < _CHAT_WITH_ATTEMPTS - 1:
                time.sleep(_CHAT_WITH_RETRY_DELAY_SECONDS)
    assert last_exc is not None
    raise last_exc


def _activate_control(control: Any) -> None:
    try:
        control.click_input()
    except (AttributeError, RuntimeError):
        control.click()
