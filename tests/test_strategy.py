from oribrink.config import StrategyConfig
from oribrink.models import AuctionData, Candidate, Quality, States, ZbRow, ZtRow
from oribrink.strategy import (
    evaluate_kanglong,
    evaluate_qianlong,
    kanglong_triggered_codes,
    select_feilong,
)

CFG = StrategyConfig()


def zt(code, lianban=None, **kw):
    return ZtRow(code=code, name=code, lianban_count=lianban, **kw)


# ------------------------------ 飞龙在天 ------------------------------ #
def test_feilong_threshold():
    rows = [zt("A", 3), zt("B", 5), zt("C", 2)]
    res, anomalies = select_feilong(rows, CFG)
    codes = {r.code for r in res}
    assert codes == {"A", "B"}  # ==3 入选, >3 入选, <3 不入选
    assert not anomalies


def test_feilong_missing_lianban_is_anomaly():
    res, anomalies = select_feilong([zt("A", None)], CFG)
    assert res == []
    assert len(anomalies) == 1


# ------------------------------ 亢龙有悔 ------------------------------ #
def _cand(code):
    return Candidate(code=code, name=code, prev_state=States.FEILONG,
                      lianban_count=3, free_market_cap=5e9)


def test_kanglong_zhaban_with_volume():
    cands = [_cand("A")]
    zb = {"A": ZbRow(code="A", name="A")}
    res, _ = evaluate_kanglong(cands, {}, zb, {"A": (200.0, 100.0)}, CFG)
    assert len(res) == 1 and res[0].state == States.KANGLONG


def test_kanglong_no_volume_not_selected():
    cands = [_cand("A")]
    zb = {"A": ZbRow(code="A", name="A")}
    res, _ = evaluate_kanglong(cands, {}, zb, {"A": (110.0, 100.0)}, CFG)
    assert res == []  # 放量倍数 1.1 < 1.5


def test_kanglong_lanban_refill():
    cands = [_cand("A")]
    zt_map = {"A": ZtRow(code="A", name="A", break_board_count=2)}
    res, _ = evaluate_kanglong(cands, zt_map, {}, {"A": (300.0, 100.0)}, CFG)
    assert len(res) == 1


def test_kanglong_late_limit_without_break_is_not_selected():
    cands = [_cand("A")]
    zt_map = {"A": ZtRow(code="A", name="A", last_limit_time="14:45:00")}
    res, _ = evaluate_kanglong(cands, zt_map, {}, {"A": (300.0, 100.0)}, CFG)
    assert res == []


def test_kanglong_missing_last_volume_anomaly():
    cands = [_cand("A")]
    zb = {"A": ZbRow(code="A", name="A")}
    res, anomalies = evaluate_kanglong(cands, {}, zb, {"A": (300.0, 0.0)}, CFG)
    assert res == [] and len(anomalies) == 1


def test_kanglong_no_trigger_skipped():
    cands = [_cand("A")]
    res, anomalies = evaluate_kanglong(cands, {}, {}, {"A": (300.0, 100.0)}, CFG)
    assert res == [] and anomalies == []  # 无弱化形态，仍是飞龙


def test_kanglong_triggered_codes_only_weak_stocks():
    cands = [_cand("A"), _cand("B"), _cand("C")]
    zt_map = {
        "A": ZtRow(code="A", name="A", break_board_count=2),     # 烂板回封
        "C": ZtRow(code="C", name="C", break_board_count=0),     # 正常封板
    }
    zb_map = {"B": ZbRow(code="B", name="B")}                     # 炸板未回封
    triggered = kanglong_triggered_codes(cands, zt_map, zb_map, CFG)
    assert triggered == {"A", "B"}  # C 无弱化形态，无需拉历史日 K


# ------------------------------ 潜龙在渊 ------------------------------ #
def _kl(code, cap):
    return Candidate(code=code, name=code, prev_state=States.KANGLONG,
                     prev_state_date="2025-05-10", free_market_cap=cap)


def test_qianlong_small_cap_qualified_and_excellent():
    small = 5e9
    au = {"A": AuctionData(code="A", price=10.6, volume=8.0),
          "B": AuctionData(code="B", price=10.6, volume=15.0)}
    lc = {"A": 10.0, "B": 10.0}
    lv = {"A": 100.0, "B": 100.0}
    res, _ = evaluate_qianlong([_kl("A", small), _kl("B", small)], au, lc, lv, CFG)
    by = {r.code: r for r in res}
    assert by["A"].quality == Quality.QUALIFIED   # 8% in (5%,10%]
    assert by["B"].quality == Quality.EXCELLENT   # 15% > 10%


def test_qianlong_gap_too_small_not_selected():
    au = {"A": AuctionData(code="A", price=10.2, volume=50.0)}
    res, _ = evaluate_qianlong([_kl("A", 5e9)], au, {"A": 10.0}, {"A": 100.0}, CFG)
    assert res == []  # 高开仅 2% < 3%


def test_qianlong_large_cap_threshold():
    big = 1e10
    au = {"A": AuctionData(code="A", price=10.6, volume=3.0),   # 3% > 2.5% 合格
          "B": AuctionData(code="B", price=10.6, volume=2.0)}   # 2% <= 2.5% 不入选
    lc = {"A": 10.0, "B": 10.0}
    lv = {"A": 100.0, "B": 100.0}
    res, _ = evaluate_qianlong([_kl("A", big), _kl("B", big)], au, lc, lv, CFG)
    assert {r.code for r in res} == {"A"}
    assert res[0].quality == Quality.QUALIFIED


def test_qianlong_missing_data_anomalies():
    res, anomalies = evaluate_qianlong(
        [_kl("A", 5e9)], {"A": None}, {"A": 10.0}, {"A": 100.0}, CFG
    )
    assert res == [] and len(anomalies) == 1
