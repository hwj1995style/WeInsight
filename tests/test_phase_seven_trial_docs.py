from __future__ import annotations

from pathlib import Path


TRIAL_DOC = Path("docs/operations/小规模试运行方案.md")
README = Path("README.md")


def test_small_scale_trial_plan_documents_limits_and_pause_rules() -> None:
    content = TRIAL_DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "核心群不超过5个" in content
    assert "公众号/订阅号不超过20个" in content
    assert "开发阶段暂时不注册 Windows 计划任务" in content
    assert "核心群等待超过阈值" in content
    assert "任一账号连续失败 3 次" in content
    assert "微信掉线、锁屏或窗口卡死" in content
    assert "group-runtime-summary" in content
    assert "article-runtime-metrics" in content
    assert "summary-daily-report-export" in content
    assert "小规模试运行方案.md" in readme
