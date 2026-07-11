from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALEOUT = ROOT / "docs" / "operations" / "微信采集管理后台扩容记录.md"
POC_RECORD = ROOT / "docs" / "operations" / "微信采集管理后台受控POC执行记录.md"


def test_scaleout_batches_are_ordered_and_unexecuted() -> None:
    content = SCALEOUT.read_text(encoding="utf-8")
    batches = ["1 群 + 1 公众号", "3 群 + 3 公众号", "5 群 + 10 公众号", "5 群 + 20 公众号"]
    positions = [content.index(item) for item in batches]
    assert positions == sorted(positions)
    assert content.count("Not Executed") >= 4
    assert "最终结论：Pending" in content
    assert "最终结论：Go" not in content
    for duration in ("24 小时", "48 小时"):
        assert duration in content


def test_scaleout_record_has_metrics_and_rollback_gates() -> None:
    content = SCALEOUT.read_text(encoding="utf-8")
    for phrase in (
        "成功率", "UI lock timeout", "核心群等待", "Worker 重启",
        "微信健康", "日报 final", "Go / Watch / No-Go", "回退批次",
        "重复运行", "并发 UI owner", "停止 article",
    ):
        assert phrase in content


def test_scaleout_stays_blocked_after_single_target_no_go() -> None:
    content = SCALEOUT.read_text(encoding="utf-8")
    poc = POC_RECORD.read_text(encoding="utf-8")
    assert "单目标 POC 明确 Go" in content
    assert "未经签署不得开始任一扩容批次" in content
    assert "决策：No-Go" in poc
    assert "扩容是否获批：否" in poc
