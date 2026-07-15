from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/单公众号订阅号真实POC运行记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md")


def test_single_article_real_poc_doc_limits_scope_and_records_results() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "1 个实际授权公众号/订阅号" in content
    assert "每轮最多 3 篇" in content
    assert "只采集当天发布数据" in content
    assert "collect-article-once" in content
    assert "parse-article-once" in content
    assert "article-runtime-metrics" in content
    assert "连续失败 3 次" in content


def test_single_article_real_poc_doc_documents_safe_runtime_boundaries() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "手动命令触发",
        "有人值守",
        "不注册 Windows 计划任务",
        "正文只运行时读取",
        "不长期保存文章正文",
        "释放微信 UI 后再解析",
        "AI 仍保持 dry-run",
        "model_called=0",
        "核心群等待超过阈值",
        "回滚到单账号模式",
    ]:
        assert keyword in content


def test_single_article_real_poc_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 58: 单公众号/订阅号真实 POC" in plan
    assert "单公众号订阅号真实POC运行记录.md" in plan
