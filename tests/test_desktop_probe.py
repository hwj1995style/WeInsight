from __future__ import annotations

from app.rpa.desktop_probe import ProcessInfo, WechatDesktopProbe, WechatHealthStatus


def test_health_ok_when_expected_version_process_exists() -> None:
    probe = WechatDesktopProbe(
        expected_version="4.1.8.107",
        process_provider=lambda: [
            ProcessInfo(process_name="WeChat", process_id=1, path="C:/WeChat/WeChat.exe", version="4.1.8.107")
        ],
    )

    health = probe.check()

    assert health.status == WechatHealthStatus.OK
    assert health.version == "4.1.8.107"


def test_health_version_mismatch() -> None:
    probe = WechatDesktopProbe(
        expected_version="4.1.8.107",
        process_provider=lambda: [
            ProcessInfo(process_name="WeChat", process_id=1, path="C:/WeChat/WeChat.exe", version="4.1.11.1")
        ],
    )

    health = probe.check()

    assert health.status == WechatHealthStatus.VERSION_MISMATCH
    assert "expected 4.1.8.107" in health.message


def test_health_not_found_when_no_wechat_process() -> None:
    probe = WechatDesktopProbe(expected_version="4.1.8.107", process_provider=lambda: [])

    health = probe.check()

    assert health.status == WechatHealthStatus.NOT_FOUND


def test_health_prefers_weixin_main_process_over_app_runtime() -> None:
    probe = WechatDesktopProbe(
        expected_version="4.1.8.107",
        process_provider=lambda: [
            ProcessInfo(process_name="WeChatAppEx", process_id=1, path="C:/runtime/WeChatAppEx.exe", version="2.5.4"),
            ProcessInfo(process_name="Weixin", process_id=2, path="D:/App/Wechat/Weixin/Weixin.exe", version="4.1.8.107"),
        ],
    )

    health = probe.check()

    assert health.status == WechatHealthStatus.OK
    assert health.process is not None
    assert health.process.process_name == "Weixin"
