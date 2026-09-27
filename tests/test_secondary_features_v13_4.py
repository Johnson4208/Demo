import math

from engine.analysis import compare
from engine.risk import assess, beneish
from engine.stock import ticker_for


def test_compare_alias_resolves_cmg_folder_to_cmc():
    result = compare(["FPT", "CMG"])
    assert result.get("error") is None
    assert [x["company"] for x in result["companies"]] == ["FPT", "CMG"]
    assert result["companies"][1]["library_company"] == "CMC"


def test_fpt_beneish_no_unit_explosion():
    result = beneish("FPT")
    assert result["status"] == "ok"
    assert -2.0 < result["score"] < -1.0
    assert 0 < result["risk_proxy_pct"] < 20
    assert 0.8 < result["components"]["DSRI"] < 1.0
    assert 0.9 < result["components"]["SGI"] < 1.3


def test_fpt_risk_consistency_has_no_false_692_percent_revenue_growth():
    result = assess("FPT")
    revenue = next(x for x in result["report_consistency"] if x["metric"] == "revenue")
    assert 0 < revenue["change_pct"] < 30


def test_cmg_alias_and_risk_are_available():
    result = assess("CMG")
    assert result["beneish"]["status"] == "ok"
    assert result["company"] == "CMG"


def test_stock_legal_aliases():
    assert ticker_for("CMC") == "CMG.VN"
    assert ticker_for("CMG") == "CMG.VN"
    assert ticker_for("VNG") == "VNZ.VN"
