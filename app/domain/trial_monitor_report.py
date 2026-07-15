from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TrialMonitorReport:
    hours: int
    markdown_body: str
    group_success_count: int
    group_failed_count: int
    group_backlog_count: int
    article_success_count: int
    article_failed_count: int
    article_backlog_count: int
    ui_lock_timeout_count: int
    generate_time: datetime


def build_trial_monitor_report(
    *,
    hours: int,
    group_success_count: int,
    group_failed_count: int,
    group_backlog_count: int,
    article_success_count: int,
    article_failed_count: int,
    article_backlog_count: int,
    ui_lock_timeout_count: int,
    generate_time: datetime,
) -> TrialMonitorReport:
    body = "\n".join(
        [
            f"# 最近 {hours} 小时双链路试运行巡检报告",
            "",
            "## 群链路",
            f"- 群链路成功数：{group_success_count}",
            f"- 群链路失败数：{group_failed_count}",
            f"- 群链路积压数：{group_backlog_count}",
            "",
            "## article 链路",
            f"- article 链路成功数：{article_success_count}",
            f"- article 链路失败数：{article_failed_count}",
            f"- article 链路积压数：{article_backlog_count}",
            "",
            "## UI 锁",
            f"- UI 锁超时数：{ui_lock_timeout_count}",
            "",
            "## 说明",
            "- 本报告只汇总试运行指标，不采集微信数据，不打开微信窗口。",
            "- 本报告不修改 group/article 链路任务状态。",
            f"- 生成时间：{generate_time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
    )
    return TrialMonitorReport(
        hours=hours,
        markdown_body=body,
        group_success_count=group_success_count,
        group_failed_count=group_failed_count,
        group_backlog_count=group_backlog_count,
        article_success_count=article_success_count,
        article_failed_count=article_failed_count,
        article_backlog_count=article_backlog_count,
        ui_lock_timeout_count=ui_lock_timeout_count,
        generate_time=generate_time,
    )
