import re
from pathlib import Path


POC_RECORD = Path("docs/operations/公众号RSS受控POC验收记录.md")


def _text() -> str:
    return POC_RECORD.read_text("utf-8")


def _section(text: str, heading: str) -> str:
    pattern = rf"(?ms)^##+\s+[^\n]*{re.escape(heading)}[^\n]*\n(.*?)(?=^##+\s|\Z)"
    match = re.search(pattern, text)
    assert match, f"missing Markdown section: {heading}"
    return match.group(1).strip()


def _table(section: str, required_headers: tuple[str, ...]) -> tuple[list[str], list[list[str]]]:
    tables = re.findall(r"(?m)(?:^\|.*\|\s*$\n)+", section)
    for block in tables:
        lines = [line for line in block.splitlines() if line.strip()]
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


def test_status_and_measured_results_are_unexecuted_blank_template():
    status = _section(_text(), "文档状态")
    assert re.search(r"状态[：:]\s*未执行", status)
    assert "真实 POC 已发生" in status and "不得填写推测值" in status

    summary = _section(_text(), "汇总结论")
    headers, rows = _table(summary, ("实测值/摘要", "证据位置", "结果（通过/不通过）"))
    for name in ("实测值/摘要", "证据位置", "结果（通过/不通过）"):
        assert set(_column(headers, rows, name)) <= {"", "____", "未评审"}
    assert not re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", summary)


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
