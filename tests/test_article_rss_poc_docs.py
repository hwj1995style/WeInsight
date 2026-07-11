import re
from pathlib import Path

import pytest


POC_RECORD = Path("docs/operations/公众号RSS受控POC验收记录.md")


def _text() -> str:
    return POC_RECORD.read_text("utf-8")


def _section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^##+\s+[^\n]*{re.escape(heading)}[^\n]*\n(.*?)(?=^##+\s|\Z)"
    match = re.search(pattern, text)
    assert match, f"missing Markdown section: {heading}"
    return match.group(1).strip()


def _table(section: str, required_headers: tuple[str, ...]) -> tuple[list[str], list[list[str]]]:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in (*section.splitlines(), ""):
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    for block in tables:
        lines = [line for line in block if line.strip()]
        headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
        if all(header in headers for header in required_headers):
            rows = [
                [cell.strip() for cell in line.strip("|").split("|")]
                for line in lines[2:]
            ]
            return headers, rows
    raise AssertionError(f"missing table headers: {required_headers}")


def _column(headers: list[str], rows: list[list[str]], name: str) -> list[str]:
    index = headers.index(name)
    return [row[index] for row in rows]


BLANK_VALUES = {"", "____", "未执行", "未评审"}


def _replace_in_section(text: str, heading: str, old: str, new: str) -> str:
    section = _section(text, heading)
    assert old in section, f"mutation target absent in {heading}: {old}"
    return text.replace(section, section.replace(old, new, 1), 1)


def _assert_blank_columns(section: str, headers: tuple[str, ...], blank_columns: tuple[str, ...]) -> None:
    actual_headers, rows = _table(section, headers)
    for name in blank_columns:
        assert set(_column(actual_headers, rows, name)) <= BLANK_VALUES, f"filled {name} in {headers[0]}"


def _assert_blank_key_values(section: str, labels: tuple[str, ...]) -> None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}[：:]\s*([^；。\n]*)", section)
        assert match, f"missing key-value field: {label}"
        assert match.group(1).strip() in BLANK_VALUES, f"filled key-value field: {label}"


def _assert_unexecuted_integrity(text: str) -> None:
    assert re.search(r"状态[：:]\s*未执行", _section(text, "文档状态"))

    basic = _section(text, "基本记录")
    headers, rows = _table(basic, ("字段", "人工填写"))
    assert set(_column(headers, rows, "人工填写")) <= BLANK_VALUES

    _assert_blank_columns(
        _section(text, "24 小时观测总表"),
        ("序号", "计划/实际轮询时间（含时区）", "新文章数", "证据位置"),
        ("计划/实际轮询时间（含时区）", "RSS HTTP/解析结果", "新文章数", "重复拦截数", "入库成功/失败数", "最早发现至入库延迟", "锁审计结果", "群探针结果", "证据位置", "执行人"),
    )
    _assert_blank_columns(
        _section(text, "RSS 完整性与时效"),
        ("RSS GUID/链接", "入库时间", "结果", "证据位置"),
        ("RSS GUID/链接", "标题", "源发布时间", "首次抓取时间", "入库时间", "延迟", "业务文章 ID", "结果", "证据位置"),
    )
    _assert_blank_key_values(
        _section(text, "业务去重"),
        ("去重键", "核对总数", "重复数", "SQL/结果证据位置", "执行人", "复核人", "结果（通过/不通过）"),
    )
    _assert_blank_key_values(
        _section(text, "UI 锁隔离"),
        ("检查时间范围", "查询语句/过滤条件", "命中数", "证据位置", "结果（通过/不通过）"),
    )
    _assert_blank_columns(
        _section(text, "WeRSS 停止检查"),
        ("检查项", "实测/时间", "证据位置", "结果（通过/不通过）"),
        ("实测/时间", "证据位置", "结果（通过/不通过）"),
    )
    _assert_blank_columns(
        _section(text, "群链路隔离"),
        ("检查点", "时间", "证据位置", "结果（通过/不通过）"),
        ("时间", "群/任务标识", "输入消息 ID", "采集结果 ID", "后处理/进度状态", "锁与错误摘要", "证据位置", "结果（通过/不通过）"),
    )
    _assert_blank_key_values(
        _section(text, "最终删除公众号 RPA 门禁"),
        ("删除执行时间", "操作者", "目标资源", "删除记录证据位置", "RSS 复测", "群链路复测", "告警复测", "删除后证据位置", "复核人", "最终状态（通过/不通过）"),
    )


def test_status_and_measured_results_are_unexecuted_blank_template():
    status = _section(_text(), "文档状态")
    assert re.search(r"状态[：:]\s*未执行", status)
    assert "真实 POC 已发生" in status and "不得填写推测值" in status

    summary = _section(_text(), "汇总结论")
    headers, rows = _table(summary, ("实测值/摘要", "证据位置", "结果（通过/不通过）"))
    for name in ("实测值/摘要", "证据位置", "结果（通过/不通过）"):
        assert set(_column(headers, rows, name)) <= {"", "____", "未评审"}
    assert not re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", summary)
    _assert_unexecuted_integrity(_text())


@pytest.mark.parametrize(
    ("heading", "old", "new"),
    (
        ("基本记录", "| 开始时间（含时区） |  |", "| 开始时间（含时区） | 2026-07-12 09:00 +08:00 |"),
        ("24 小时观测总表", "| 1 |  |", "| 1 | 2026-07-12 09:15 +08:00 |"),
        ("RSS 完整性与时效", "| ____ | ____ | ____ | ____ | ____ | ____ | ____ | ____ | ____ |", "| ____ | ____ | ____ | ____ | ____ | ____ | ____ | ____ | /tmp/evidence |"),
        ("业务去重", "重复数：____", "重复数：1"),
        ("UI 锁隔离", "命中数：____", "命中数：0"),
        ("WeRSS 停止检查", "| WeRSS 停止与告警 |  |  |  |", "| WeRSS 停止与告警 | 2026-07-12 10:00 | /tmp/log | 通过 |"),
        ("群链路隔离", "| 窗口前 |  |", "| 窗口前 | 2026-07-12 09:00 |"),
        ("最终删除公众号 RPA 门禁", "删除执行时间：____", "删除执行时间：2026-07-13 10:00 +08:00"),
        ("最终删除公众号 RPA 门禁", "RSS 复测：____", "RSS 复测：通过"),
    ),
)
def test_unexecuted_integrity_validator_rejects_injected_measurements(heading, old, new):
    mutated = _replace_in_section(_text(), heading, old, new)
    with pytest.raises(AssertionError):
        _assert_unexecuted_integrity(mutated)


def test_admission_and_final_decisions_use_explicit_binary_values_and_start_blank():
    admission = _section(_text(), "准入冻结")
    assert "仅允许填写“通过”或“不通过”" in admission
    assert re.search(r"准入决定（通过/不通过）[：:]\s*(?:____|未评审)", admission)

    summary = _section(_text(), "汇总结论")
    assert "最终结论仅允许填写“通过”或“不通过”" in summary
    assert re.search(r"最终结论（通过/不通过）[：:]\s*(?:____|未评审)", summary)


def test_24_hour_continuity_and_15_minute_sla_are_scoped_correctly():
    observation = _section(_text(), "24 小时观测总表")
    assert "连续 24 小时" in observation
    assert "证据缺口" in observation

    rss = _section(_text(), "RSS 完整性与时效")
    assert "15 分钟内" in rss
    assert "超过 15 分钟" in rss
    _table(rss, ("首次抓取时间", "入库时间", "延迟", "证据位置"))


def test_werss_stop_section_co_locates_isolation_continuity_and_recovery_evidence():
    werss = _section(_text(), "WeRSS 停止检查")
    for requirement in (
        "微信群仍正常",
        "不得触发 UI/RPA 兜底",
        "不获取 wechat_ui_lock",
        "恢复后首次成功时间",
        "补采核对",
        "恢复证据位置",
    ):
        assert requirement in werss
    _table(werss, ("检查项", "实测/时间", "证据位置", "结果（通过/不通过）"))


def test_execution_sections_use_consistent_binary_result_labels():
    for heading in ("业务去重", "UI 锁隔离", "群链路隔离"):
        section = _section(_text(), heading)
        assert "通过/失败" not in section
        assert "结果（通过/不通过）" in section


def test_each_gate_has_auditable_columns_and_empty_evidence_fields():
    admission = _section(_text(), "准入冻结")
    headers, rows = _table(
        admission,
        ("冻结门禁", "明确通过标准", "结果（通过/不通过）", "核验时间", "执行人", "复核人", "证据位置/校验值"),
    )
    assert len(rows) >= 8
    for name in ("结果（通过/不通过）", "核验时间", "执行人", "复核人", "证据位置/校验值"):
        assert set(_column(headers, rows, name)) <= {"", "____", "未评审"}


def test_rpa_deletion_gate_orders_approval_before_delete_and_requires_failed_postcheck_rollback():
    deletion = _section(_text(), "最终删除公众号 RPA 门禁")
    poc_pass = deletion.index("POC 最终通过")
    approvals = deletion.index("产品、研发、运维与风险责任人明确批准")
    deletion_action = deletion.index("删除执行时间")
    assert poc_pass < deletion_action and approvals < deletion_action
    assert "任一复测不通过" in deletion
    assert "立即回滚" in deletion
    assert "整体验收改判不通过" in deletion

    headers, rows = _table(deletion, ("删除前置条件", "结果（通过/不通过）", "审批/证据位置及校验值", "责任人", "时间"))
    assert all(not row[headers.index("审批/证据位置及校验值")] for row in rows)
