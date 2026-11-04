import pandas as pd

from p2pmining import quality, tobe


def test_simulation_never_goes_below_delivery_time():
    cases = pd.DataFrame({"cycle_days": [50.0, 10.0], "po_to_gr_days": [5.0, 8.0]})
    savings = pd.DataFrame({"O1": [20.0, 30.0], "O2": [10.0, 0.0]})
    new = tobe.simulate(cases, savings)
    assert list(new) == [20.0, 8.0]


def test_capped_excess_against_peers():
    cases = pd.DataFrame(
        {
            "item_category": ["x"] * 80,
            "flag": [True] * 40 + [False] * 40,
            "stage": [30.0] * 20 + [100.0] * 20 + [10.0] * 40,
        }
    )
    s = tobe._capped_excess(cases, "flag", "stage")
    # peer median 10, flagged median 65 -> cap 55; 30-day cases save 20, 100-day cases save 55
    assert s.iloc[0] == 20 and s.iloc[30] == 55 and s.iloc[50] == 0


def test_every_opportunity_has_a_written_assumption():
    for oid, a in tobe.ASSUMPTIONS.items():
        assert a["assumption"] and a["lever"] and a["effort"] in {"Low", "Medium", "High"}, oid


def test_tobe_run_on_synthetic(synth, paths):
    clean = quality.clean(synth, quality.assess(synth, check_fingerprint=False))
    s = tobe.run(clean, paths)
    assert s["target"]["median_cycle_days"] <= s["baseline"]["median_cycle_days"]
    assert (paths.models / "to_be.bpmn").exists()
    assert (paths.figures / "kpi_dashboard.png").exists()
