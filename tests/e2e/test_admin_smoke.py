import uuid
import re
import time
from datetime import datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect


def _reload_until_contains(page, text: str, timeout_ms: int = 60_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1_000
    while time.monotonic() < deadline:
        page.reload()
        if text in page.locator("body").inner_text():
            return
        page.wait_for_timeout(500)
    raise AssertionError(f"timed out waiting for {text!r}")


def test_fake_admin_login_to_report_smoke(admin_base_url, browser):
    prefix = f"E2E-{uuid.uuid4().hex[:10]}"
    targets = [f"{prefix}-A", f"{prefix}-B"]
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    console = []
    pageerrors = []
    page.on("console", lambda item: console.append(item.text) if item.type == "error" else None)
    page.on("pageerror", lambda error: pageerrors.append(str(error)))

    page.goto(f"{admin_base_url}/login")
    page.get_by_label("用户名").fill("admin")
    page.get_by_label("密码").fill("admin123456")
    page.get_by_role("button", name="登录").click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_text("默认密码", exact=False)).to_be_visible()

    for target in targets:
        page.goto(f"{admin_base_url}/sources/groups/new")
        page.get_by_label("群名称").fill(target)
        page.get_by_label("优先级").fill("10")
        page.get_by_label("默认采集间隔（秒）").fill("30")
        page.get_by_label("回溯页数", exact=True).fill("1")
        page.get_by_label("额外回溯页数", exact=True).fill("0")
        page.get_by_role("button", name="保存配置").click()
        expect(page.get_by_text(target, exact=True)).to_be_visible()

    now = datetime.now().replace(second=0, microsecond=0)
    page.goto(f"{admin_base_url}/jobs/new?pipeline=group")
    page.get_by_label("任务名称").fill(prefix + "-job")
    for target in targets:
        page.get_by_label(target, exact=False).check()
    page.get_by_label("整体开始时间").fill((now - timedelta(minutes=1)).isoformat(timespec="minutes"))
    page.get_by_label("整体结束时间").fill((now + timedelta(minutes=30)).isoformat(timespec="minutes"))
    page.get_by_label("每日窗口开始").fill("00:00")
    page.get_by_label("每日窗口结束").fill("00:00")
    page.get_by_label("采集频率（秒）").fill("30")
    page.get_by_role("button", name="创建任务").click()
    expect(page.get_by_text(prefix + "-job", exact=True)).to_be_visible()
    job_detail_url = page.url

    page.goto(f"{admin_base_url}/runs")
    _reload_until_contains(page, prefix + "-job")
    expect(page.locator("body")).not_to_contain_text("<img src=\"file:")
    page.goto(job_detail_url)
    page.get_by_role("button", name="停止任务").click()
    expect(page.locator("body")).to_contain_text("停止", timeout=30_000)
    page.goto(f"{admin_base_url}/reports")
    page.get_by_label("生成类型").select_option("all")
    page.get_by_role("button", name="提交生成请求").click()
    expect(page.locator(".request-status")).to_contain_text(
        re.compile("成功|部分成功"), timeout=60_000
    )
    page.goto(f"{admin_base_url}/reports")
    expect(page.locator("body")).to_contain_text("临时版")

    page.set_viewport_size({"width": 390, "height": 844})
    for route in ("/dashboard", "/sources/groups", "/jobs", "/runs", "/reports"):
        page.goto(admin_base_url + route)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert console == []
    assert pageerrors == []
    context.close()
