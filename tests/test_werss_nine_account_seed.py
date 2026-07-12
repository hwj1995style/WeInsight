from pathlib import Path
import re

ROOT = Path(__file__).parents[1]


def test_nine_account_seed_is_explicit_and_only_hunan_enters_downstream():
    sql = (ROOT / "sql/deploy/20260712_seed_werss_nine_accounts.sql").read_text(encoding="utf-8")
    names = ["河南金咕咕蛋品", "江西九江褐壳蛋", "成都鸡蛋价格", "蓝天禽蛋联盟", "贵阳鸡蛋价格", "河北辛集城方蛋品", "湖南三尖农牧公司", "河北馆陶鸡蛋报价", "家美鲜鸡蛋 佳美鲜"]
    assert all(name in sql for name in names)
    assert sql.count("MP_WXS_") == 9
    assert "江西九江祺壳蛋" not in sql
    assert len(re.findall(r"'rss',\s*1,\s*1,", sql)) == 1
    assert len(re.findall(r"'rss',\s*1,\s*0,", sql)) == 8
    assert "ON DUPLICATE KEY UPDATE" in sql
