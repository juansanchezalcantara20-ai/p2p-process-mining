import numpy as np
import pandas as pd

from p2pmining import quality, rootcause


def test_lift_table_and_rules_recover_planted_effect():
    rng = np.random.default_rng(0)
    n = 4000
    f = pd.DataFrame(
        {
            "spend_area": rng.choice(["A", "B", "C"], n),
            "payment_block": rng.random(n) < 0.3,
        }
    )
    # slow only when area C and blocked
    f["slow"] = (f["spend_area"] == "C") & f["payment_block"] | (rng.random(n) < 0.05)
    lifts, base = rootcause.lift_table(f, "slow", ["spend_area", "payment_block"])
    assert set(lifts.head(2)["value"]) == {"C", "True"}
    assert "False" not in set(lifts["value"])
    model, X, rules, imp, metrics = rootcause.fit_tree(f, "slow", ["spend_area", "payment_block"])
    top = rules.iloc[0]["rule"]
    assert "spend area is C" in top and "payment was blocked" in top
    assert metrics["roc_auc_test"] > 0.8


def test_phrase_handles_sets_and_booleans():
    u = {"Q1", "Q2", "Q3", "Q4"}
    assert rootcause._phrase("po_value_band", {"Q1", "Q2"}, u) == "PO item value is Q1 or Q2"
    assert rootcause._phrase("po_value_band", {"Q1", "Q2", "Q3"}, u) == "PO item value is not Q4"
    assert rootcause._phrase("payment_block", {"False"}, {"True", "False"}) == "no payment block"
    assert rootcause._phrase("payment_block", u, u) is None


def test_rootcause_run_on_synthetic(synth, paths):
    clean = quality.clean(synth, quality.assess(synth, check_fingerprint=False))
    s = rootcause.run(clean, paths)
    assert 0.2 < s["slow_order"]["base_rate"] < 0.3
    assert (paths.results / "rootcause" / "tree_rules_slow_order.csv").exists()
