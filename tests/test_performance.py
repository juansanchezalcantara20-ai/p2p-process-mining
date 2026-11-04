from p2pmining import config as C
from p2pmining import performance, quality
from tests.conftest import make_log


def test_case_table_cycle_and_stages():
    df = make_log(
        {
            "a": [
                (C.PO, "2018-02-01"),
                (C.VCI, "2018-02-03"),
                (C.GR, "2018-02-05"),
                (C.IR, "2018-02-10"),
                (C.CLEAR, "2018-03-12"),
            ]
        }
    )
    ct = performance.case_table(df.assign(status="complete"))
    row = ct.loc["a"]
    assert row["cycle_days"] == 39
    assert row["po_to_gr_days"] == 4
    assert row["invoice_capture_days"] == 7
    assert row["match_to_clear_days"] == 30


def test_consignment_ends_at_last_goods_receipt():
    df = make_log(
        {"c": [(C.PO, "2018-02-01"), (C.GR, "2018-02-05"), (C.GR, "2018-02-11")]},
        category=C.CAT_CONSIGNMENT,
    )
    ct = performance.case_table(df.assign(status="complete"))
    assert ct.loc["c", "cycle_days"] == 10


def test_describe_uses_percentiles():
    import pandas as pd

    d = performance.describe(pd.Series([1, 2, 3, 4, 100]))
    assert d["median"] == 3 and d["mean"] == 22


def test_performance_run_on_synthetic(synth, paths):
    clean = quality.clean(synth, quality.assess(synth, check_fingerprint=False))
    s = performance.run(clean, paths)
    assert s["cycle_invoice"]["median"] > 0
    # the synthetic generator injects payment blocks that delay clearing
    assert s["payment_block"]["median_with"] > s["payment_block"]["median_without"]
    assert (paths.figures / "waiting_pareto.png").exists()
