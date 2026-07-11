from pathlib import Path


POC_RECORD = Path("docs/operations/公众号RSS受控POC验收记录.md")


def test_poc_record_contains_required_gates():
    text = POC_RECORD.read_text("utf-8")
    for item in (
        "连续 24 小时",
        "15 分钟内",
        "无重复业务文章",
        "不获取 wechat_ui_lock",
        "WeRSS 停止",
        "微信群仍正常",
        "最终删除公众号 RPA",
    ):
        assert item in text


def test_poc_record_is_an_unexecuted_auditable_template():
    text = POC_RECORD.read_text("utf-8")
    for item in (
        "未执行",
        "不得填写推测值",
        "开始时间（含时区）",
        "结束时间（含时区）",
        "证据位置",
        "执行人",
        "复核人",
        "通过/失败",
    ):
        assert item in text


def test_poc_record_covers_freeze_isolation_and_deletion_rules():
    text = POC_RECORD.read_text("utf-8")
    for item in (
        "准入冻结",
        "RSS",
        "UI 锁隔离",
        "群链路隔离",
        "停止并判失败",
        "删除前置条件",
        "删除后证据",
        "不得删除",
    ):
        assert item in text
