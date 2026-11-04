import pandas as pd

from p2pmining import config as C
from p2pmining import conformance, quality
from tests.conftest import make_log


def _flags(traces, category=C.CAT_3W_AFTER):
    return conformance.rule_flags(make_log(traces, category=category))


def test_three_way_match_rule():
    f = _flags(
        {
            "ok": [
                (C.PO, "2018-01-01"),
                (C.GR, "2018-01-05"),
                (C.IR, "2018-01-06"),
                (C.CLEAR, "2018-02-01"),
            ],
            "nogr": [(C.PO, "2018-01-01"), (C.IR, "2018-01-06"), (C.CLEAR, "2018-02-01")],
            "open": [(C.PO, "2018-01-01"), (C.GR, "2018-01-05")],
        }
    )
    assert f.loc["ok", "R1_no_three_way_match"] == 0
    assert f.loc["nogr", "R1_no_three_way_match"] == 1
    assert pd.isna(f.loc["open", "R1_no_three_way_match"])  # not paid -> not applicable
    assert f.loc["nogr", "R2_invoice_before_gr"] == 1


def test_changes_blocks_and_after_the_fact():
    f = _flags(
        {
            "x": [
                (C.VCI, "2017-12-20 23:59"),
                (C.PO, "2018-01-01"),
                (C.CHANGE_PRICE, "2018-01-02"),
                (C.GR, "2018-01-05"),
                (C.IR, "2018-01-06"),
                (C.REMOVE_BLOCK, "2018-01-20"),
                (C.CLEAR, "2018-02-01"),
            ],
        },
        category=C.CAT_3W_BEFORE,
    )
    row = f.loc["x"]
    assert row["R3_price_change_after_po"] and not row["R4_quantity_change_after_po"]
    assert row["R5_payment_block"] and row["R6_after_the_fact_po"]
    assert pd.isna(row["R2_invoice_before_gr"])  # rule only for 'invoice after GR'


def test_same_day_vendor_invoice_is_not_after_the_fact():
    f = _flags(
        {"y": [(C.PO, "2018-01-01 10:00"), (C.VCI, "2018-01-01 00:00")]}, category=C.CAT_3W_BEFORE
    )
    assert not f.loc["y", "R6_after_the_fact_po"]


def test_token_replay_flags_extra_activities():
    df = make_log(
        {
            "fit": [
                (C.PO, "2018-01-01"),
                (C.VCI, "2018-01-02"),
                (C.GR, "2018-01-03"),
                (C.IR, "2018-01-04"),
                (C.CLEAR, "2018-02-01"),
            ],
            "block": [
                (C.PO, "2018-01-01"),
                (C.GR, "2018-01-03"),
                (C.IR, "2018-01-04"),
                (C.REMOVE_BLOCK, "2018-01-10"),
                (C.CLEAR, "2018-02-01"),
            ],
            "early_clear": [
                (C.PO, "2018-01-01"),
                (C.IR, "2018-01-04"),
                (C.CLEAR, "2018-01-05"),
                (C.GR, "2018-01-06"),
            ],
        },
        category=C.CAT_3W_BEFORE,
    )
    tr = conformance.token_replay(df)
    assert bool(tr.loc["fit", "fits"])
    assert not tr.loc["block", "fits"] and tr.loc["block", "extra_activities"]
    assert not tr.loc["early_clear", "fits"]


def test_conformance_run_on_synthetic(synth, paths):
    clean = quality.clean(synth, quality.assess(synth, check_fingerprint=False))
    s = conformance.run(clean, paths)
    rates = {r["rule"]: r["violation_rate"] for r in s["impact"]}
    assert rates["R5_payment_block"] > 0.1  # injected at 20%
    assert rates["R3_price_change_after_po"] > 0.05  # injected at 15%
    assert 0 < s["conforming_share"] < 1
