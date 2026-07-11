from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "operations" / "微信采集管理后台受控POC验收清单.md"
RECORD = ROOT / "docs" / "operations" / "微信采集管理后台受控POC执行记录.md"
README = ROOT / "README.md"


def test_admin_poc_docs_keep_real_collection_gated() -> None:
    combined = CHECKLIST.read_text(encoding="utf-8") + RECORD.read_text(encoding="utf-8")
    for phrase in ("微信 PC 4.1.8.107", "第一轮只允许 1 个核心群和 1 个公众号", "人工值守", "Go / Watch / No-Go", "次日 00:10", "回滚", "Not Executed"):
        assert phrase in combined


def test_checklist_preserves_order_and_article_limits() -> None:
    content = CHECKLIST.read_text(encoding="utf-8")
    markers = ["### 1. 完整自动化回归", "### 2. 只读上线前检查", "### 3. Fake RPA 全量验收", "### 4. 单核心群真实 POC", "### 5. 单公众号真实 POC", "### 6. 双链路交错运行", "### 7. 次日 00:10", "### 8. Go / Watch / No-Go"]
    positions = [content.index(marker) for marker in markers]
    assert positions == sorted(positions)
    for phrase in ("30 分钟", "至少 10 分钟", "每轮最多 1 篇", "1 到 2 小时"):
        assert phrase in content


def test_record_does_not_record_go_without_evidence() -> None:
    content = RECORD.read_text(encoding="utf-8")
    assert "当前状态：Completed (No-Go)" in content
    assert "决策：No-Go" in content
    assert "决策：Go" not in content
    assert "真实 POC 已通过" not in content
    for phrase in ("run ID", "UI lock", "停止耗时", "本机截图路径", "回滚"):
        assert phrase in content


def test_readme_links_controlled_poc_documents() -> None:
    content = README.read_text(encoding="utf-8")
    assert "微信采集管理后台受控POC验收清单.md" in content
    assert "微信采集管理后台受控POC执行记录.md" in content
    assert "未经人工批准不得执行真实微信 POC" in content


def test_admin_poc_record_names_direct_public_account_search_gate() -> None:
    content = RECORD.read_text(encoding="utf-8")

    assert "直接搜索公众号分类精确匹配" in content
    assert "重跑单目标 POC" in content
    assert "搜索网络结果" not in content
