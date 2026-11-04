import pandas as pd

from p2pmining import config as C
from p2pmining import ingest, quality
from tests.conftest import make_log


def test_csv_is_decoded_as_cp1252_and_canonicalised():
    header = '"eventID ","case concept:name","event concept:name","event time:timestamp",'
    header += '"case Spend area text","event Cumulative net worth (EUR)"\n'
    row = '"1","A_1","Create Purchase Order Item","03-01-2018 17:37:00.000",'
    row += '"Resins \u2013 Liquid",5.0\n'
    raw = (header + row).encode("cp1252")
    df = ingest._canonicalise(ingest.read_csv_bytes(raw))
    assert list(df.columns[:3]) == ["event_id", "case_id", "activity"]
    assert df.loc[0, "timestamp"] == pd.Timestamp("2018-01-03 17:37")
    assert df.loc[0, "spend_area"] == "Resins – Liquid"
    assert df.loc[0, "net_worth_eur"] == 5.0


def test_activity_label_normalisation():
    assert quality.canonical_activity_name("Change payment term") == "Change Payment Term"
    assert (
        quality.canonical_activity_name("Change Approval for Purchase Order")
        == "Change Approval for Purchase Order"
    )
    assert quality.canonical_activity_name("  Clear   Invoice ") == "Clear Invoice"
    issues = quality.activity_name_issues(
        pd.Series(["Clear Invoice", "clear invoice", "Change payment term"])
    )
    assert issues["near_duplicate_groups"] == [["Clear Invoice", "clear invoice"]]
    assert issues["casing_inconsistent"] == ["Change payment term"]


def test_cleaning_removes_out_of_window_cases_and_exact_duplicates():
    df = make_log(
        {
            "ok": [
                (C.PO, "2018-02-01 10:00"),
                (C.GR, "2018-02-05 10:00"),
                (C.GR, "2018-02-05 10:00"),
                (C.IR, "2018-02-06 10:00"),
                (C.CLEAR, "2018-03-01 10:00"),
            ],
            "bad": [(C.PO, "2018-02-01 10:00"), (C.VCI, "1948-01-26 23:59")],
        }
    )
    df.loc[2, "event_id"] = "dup"  # same content, distinct id -> exact duplicate
    rep = quality.assess(df, check_fingerprint=False)
    assert rep.timestamps["outside_window_cases"] == 1
    assert rep.duplicates["exact_duplicate_extra_events"] == 1
    out = quality.clean(df, rep)
    assert set(out["case_id"]) == {"ok"}
    assert (out["activity"] == C.GR).sum() == 1
    assert out["status"].iloc[0] == "complete"


def test_ties_are_broken_by_canonical_position():
    df = make_log({"t": [(C.CLEAR, "2018-02-01 00:00"), (C.PO, "2018-02-01 00:00")]})
    rep = quality.assess(df, check_fingerprint=False)
    out = quality.clean(df, rep)
    assert list(out["activity"]) == [C.PO, C.CLEAR]


def test_case_status_rules():
    df = make_log(
        {
            "done": [(C.PO, "2018-01-01"), (C.CLEAR, "2018-02-01")],
            "open": [(C.PO, "2018-01-01"), (C.GR, "2018-02-01")],
            "del": [(C.PO, "2018-01-01"), (C.DELETE_ITEM, "2018-02-01")],
            "react": [
                (C.PO, "2018-01-01"),
                (C.DELETE_ITEM, "2018-02-01"),
                (C.REACTIVATE_ITEM, "2018-02-02"),
            ],
        }
    )
    st = quality.case_status(df)
    assert st.to_dict() == {"del": "cancelled", "done": "complete", "open": "open", "react": "open"}


def test_quality_run_on_synthetic(synth, paths):
    out = quality.run(synth, paths, check_fingerprint=False)
    assert (paths.results / "quality" / "quality_report.json").exists()
    assert (paths.figures / "quality_issues.png").exists()
    assert out["status"].isin(["complete", "open", "cancelled"]).all()


def test_sample_reads_through_same_path():
    df = ingest.read_raw(C.DATA_SAMPLE / "bpi2019_sample.csv.gz")
    assert df["case_id"].nunique() > 2000
    assert df["item_category"].nunique() == 4
    assert df["timestamp"].notna().all()
