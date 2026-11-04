import pandas as pd

from p2pmining import config as C
from p2pmining import discovery, quality
from tests.conftest import make_log


def test_happy_path_rules():
    assert discovery.is_happy(" > ".join([C.PO, C.VCI, C.GR, C.IR, C.CLEAR]), C.CAT_3W_BEFORE)
    assert discovery.is_happy(" > ".join([C.PR, C.PO, C.GR, C.VCI, C.IR, C.CLEAR]), C.CAT_3W_AFTER)
    assert not discovery.is_happy(
        " > ".join([C.PO, C.VCI, C.GR, C.IR, C.REMOVE_BLOCK, C.CLEAR]), C.CAT_3W_BEFORE
    )
    assert discovery.is_happy(" > ".join([C.PO, C.GR]), C.CAT_CONSIGNMENT)


def test_transitions_and_dfg_waiting_time():
    df = make_log(
        {
            "a": [(C.PO, "2018-01-01"), (C.GR, "2018-01-03"), (C.IR, "2018-01-04")],
            "b": [(C.PO, "2018-01-01"), (C.GR, "2018-01-05")],
        }
    )
    edges = discovery.dfg_table(df).set_index(["source", "target"])
    assert edges.loc[(C.PO, C.GR), "count"] == 2
    assert edges.loc[(C.PO, C.GR), "median_days"] == 3.0
    assert edges.loc[(C.GR, C.IR), "total_days"] == 1.0


def test_variant_coverage_is_monotonic(synth):
    vt, seq = discovery.variant_table(synth)
    assert vt["cumulative_share"].is_monotonic_increasing
    assert abs(vt["share"].sum() - 1) < 1e-9
    assert len(seq) == synth["case_id"].nunique()


def test_discovery_run_on_synthetic(synth, paths):
    clean = quality.clean(synth, quality.assess(synth, check_fingerprint=False))
    s = discovery.run(clean, paths)
    assert 0 < s["model"]["log_fitness"] <= 1
    assert (paths.models / "as_is_inductive_core.bpmn").exists()
    assert (paths.figures / "dfg_performance.png").exists()
    assert isinstance(pd.read_csv(paths.results / "discovery" / "dfg_edges.csv"), pd.DataFrame)
