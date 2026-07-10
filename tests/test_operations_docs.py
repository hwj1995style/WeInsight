from __future__ import annotations

from pathlib import Path


def test_phase3_plan_lists_operational_tasks() -> None:
    plan = Path("docs/superpowers/plans/2026-07-03-微信信息采集分析系统第三阶段运维化计划.md")

    assert plan.exists()
    content = plan.read_text(encoding="utf-8")

    for task_name in [
        "Task 16: 运行手册与验收清单",
        "Task 17: 任务重跑与补偿工具",
        "Task 18: 失败任务查看与死信管理",
        "Task 19: 群链路试运行监控指标",
        "Task 20: 日报质量增强",
        "Task 21: 生产配置模板",
        "Task 22: 数据库初始化与升级脚本整理",
        "Task 23: 长稳运行脚本增强",
        "Task 24: 数据安全与脱敏回归检查",
        "Task 25: 公众号/订阅号链路启动前设计复核",
    ]:
        assert task_name in content


def test_group_operations_runbook_covers_required_workflows() -> None:
    runbook = Path("docs/operations/微信群链路运行手册与验收清单.md")

    assert runbook.exists()
    content = runbook.read_text(encoding="utf-8")

    for section in [
        "## 1. 适用范围",
        "## 2. 环境前置检查",
        "## 3. 初始化与配置",
        "## 4. 手动运行流程",
        "## 5. 巡检与验收清单",
        "## 6. 故障恢复",
        "## 7. 禁止事项",
    ]:
        assert section in content

    for command in [
        "wechat-health",
        "group-config-list",
        "run-group-pipeline-once",
        "group-runtime-summary",
        "group-runtime-metrics",
        "group-task-list",
        "group-task-reset",
        "group-task-reset-date",
        "group-task-failed-list",
        "group-task-retry-failed",
        "group-daily-report-export",
    ]:
        assert command in content

    assert "不注册 Windows 计划任务" in content
    assert "不输出消息正文" in content
