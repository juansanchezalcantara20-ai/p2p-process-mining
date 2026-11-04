"""Phase 5 - root cause: which case attributes go with long cycle times or deviations?

Two deliberately simple tools, chosen so that a process owner can check the reasoning:

* **Lift tables** - for each attribute value, the share of "slow" (or deviating) cases versus
  the overall share. A lift of 2.0 means "twice as likely as the average item".
* **Shallow decision trees** (depth 3) whose leaves are translated into plain-language rules
  with their support (how many items) and rate.

Two feature sets are kept apart on purpose:

* *order-time* attributes known when the PO is created (category, spend area, vendor size,
  value, requisition, document type) - these say **where** to look;
* *process* behaviours observed later (payment block, price change, partial deliveries...) -
  these say **what happens** to the slow items. Mixing them would let the tree "explain"
  slowness with events that are partly its consequence.

Associations are not proof of causation; the report says so next to every claim.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, _tree, plot_tree

from . import config as C
from . import viz

ORDER_FEATURES = [
    "item_category",
    "spend_area",
    "document_type",
    "item_type",
    "vendor_size",
    "po_value_band",
    "has_requisition",
    "srm_origin",
]
PROCESS_FEATURES = [
    "payment_block",
    "price_change",
    "quantity_change",
    "invoice_cancelled",
    "multiple_goods_receipts",
    "multiple_invoices",
    "invoice_before_goods",
    "after_the_fact_po",
]
LABELS = {
    "item_category": "item category",
    "spend_area": "spend area",
    "document_type": "document type",
    "item_type": "item type",
    "vendor_size": "vendor size",
    "po_value_band": "PO item value",
    "has_requisition": "started from a purchase requisition",
    "srm_origin": "created through the SRM portal",
    "payment_block": "payment was blocked",
    "price_change": "price changed after the PO",
    "quantity_change": "quantity changed after the PO",
    "invoice_cancelled": "an invoice receipt was cancelled",
    "multiple_goods_receipts": "goods arrived in several receipts",
    "multiple_invoices": "invoiced in several invoices",
    "invoice_before_goods": "invoice posted before the goods arrived",
    "after_the_fact_po": "vendor invoice dated before the PO",
}


def build_features(clean: pd.DataFrame) -> pd.DataFrame:
    from .conformance import rule_flags
    from .performance import case_table

    df = clean[clean["status"] != "cancelled"]
    ct = case_table(df)
    flags = rule_flags(df)
    a = df["activity"]
    cnt = (
        pd.DataFrame(
            {
                "case_id": df["case_id"],
                "gr": a == C.GR,
                "ir": a == C.IR,
                "srm": a.str.startswith("SRM:"),
            }
        )
        .groupby("case_id", sort=False)
        .sum()
    )
    f = pd.DataFrame(index=ct.index)
    f["item_category"] = ct["item_category"]
    top_areas = ct["spend_area"].value_counts().head(10).index
    f["spend_area"] = ct["spend_area"].where(ct["spend_area"].isin(top_areas), "Other")
    f["document_type"] = ct["document_type"]
    f["item_type"] = ct["item_type"]
    vendor_n = ct.groupby("vendor")["item_category"].transform("size")
    f["vendor_size"] = pd.cut(
        vendor_n,
        [0, 50, 500, 5000, np.inf],
        labels=["small (<50 items)", "medium (50-500)", "large (500-5k)", "top (>5k items)"],
    ).astype(str)
    q = ct["value"].quantile([0.25, 0.5, 0.75]).to_numpy()
    f["po_value_band"] = pd.cut(
        ct["value"].fillna(0),
        [-np.inf, q[0], q[1], q[2], np.inf],
        labels=[
            f"Q1 (< EUR {q[0]:,.0f})",
            f"Q2 (EUR {q[0]:,.0f}-{q[1]:,.0f})",
            f"Q3 (EUR {q[1]:,.0f}-{q[2]:,.0f})",
            f"Q4 (> EUR {q[2]:,.0f})",
        ],
    ).astype(str)
    f["has_requisition"] = ct["pr"].notna()
    f["srm_origin"] = cnt["srm"].reindex(f.index) > 0
    f["payment_block"] = flags["R5_payment_block"].fillna(False).astype(bool)
    f["price_change"] = flags["R3_price_change_after_po"].astype(bool)
    f["quantity_change"] = flags["R4_quantity_change_after_po"].astype(bool)
    f["invoice_cancelled"] = flags["R7_invoice_cancelled"].fillna(False).astype(bool)
    f["multiple_goods_receipts"] = cnt["gr"].reindex(f.index) > 1
    f["multiple_invoices"] = cnt["ir"].reindex(f.index) > 1
    f["invoice_before_goods"] = ct["ir"].notna() & (ct["gr"].isna() | (ct["ir"] < ct["gr"]))
    f["after_the_fact_po"] = flags["R6_after_the_fact_po"].fillna(False).astype(bool)
    f["any_deviation"] = flags.fillna(False).astype(bool).any(axis=1)
    f["cycle_days"] = ct["cycle_days"]
    f["match_to_clear_days"] = ct["match_to_clear_days"]
    f["po_to_gr_days"] = ct["po_to_gr_days"]
    f["n_vendor_items"] = vendor_n
    f["status"] = ct["status"]
    f["in_cohort"] = (ct["po"] >= C.COHORT_START) & (ct["po"] < C.COHORT_END)
    f["value"] = ct["value"]
    return f


def lift_table(f: pd.DataFrame, target: str, features: list[str], min_support: float = 0.01):
    base = f[target].mean()
    rows = []
    for col in features:
        for val, g in f.groupby(col, observed=True)[target]:
            if str(val) == "False" or len(g) < min_support * len(f):
                continue
            rows.append(
                {
                    "attribute": LABELS.get(col, col),
                    "value": str(val),
                    "cases": int(len(g)),
                    "rate": float(g.mean()),
                    "lift": float(g.mean() / base) if base else np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values("lift", ascending=False).reset_index(drop=True), base


NEGATIONS = {
    "has_requisition": "no purchase requisition",
    "srm_origin": "not created through SRM",
    "payment_block": "no payment block",
    "price_change": "no price change",
    "quantity_change": "no quantity change",
    "invoice_cancelled": "no invoice cancellation",
    "multiple_goods_receipts": "a single goods receipt",
    "multiple_invoices": "a single invoice",
    "invoice_before_goods": "goods arrived before the invoice was posted",
    "after_the_fact_po": "PO existed before the vendor invoice",
}


def _phrase(col: str, allowed: set[str], universe: set[str]) -> str | None:
    """Describe the set of values a rule allows for one attribute, in business language."""
    if allowed == universe:
        return None
    label = LABELS.get(col, col)
    if universe <= {"True", "False"}:
        return label if allowed == {"True"} else NEGATIONS.get(col, f"not {label}")
    if len(allowed) == 1:
        return f"{label} is {next(iter(allowed))}"
    excluded = universe - allowed
    if len(excluded) < len(allowed):
        return f"{label} is not " + " / ".join(sorted(excluded))
    return f"{label} is " + " or ".join(sorted(allowed))


def tree_rules(
    model: DecisionTreeClassifier,
    names: list[str],
    leaf_rate: np.ndarray,
    leaf_cases: np.ndarray,
    base: float,
) -> pd.DataFrame:
    """Leaves as plain-language rules with support and (unweighted) rate on all cases."""
    t = model.tree_
    universe: dict[str, set[str]] = {}
    for nm in names:
        col, val = nm.split("=", 1)
        universe.setdefault(col, set()).add(val)
    rows = []

    def walk(node: int, allowed: dict[str, set[str]]) -> None:
        if t.feature[node] == _tree.TREE_UNDEFINED:
            parts = [_phrase(c, allowed[c], universe[c]) for c in universe]
            parts = [p for p in parts if p]
            rows.append(
                {
                    "rule": " AND ".join(parts) if parts else "all items",
                    "cases": int(leaf_cases[node]),
                    "rate": float(leaf_rate[node]),
                    "lift": float(leaf_rate[node] / base) if base else np.nan,
                }
            )
            return
        col, val = names[t.feature[node]].split("=", 1)
        left = {k: set(v) for k, v in allowed.items()}
        left[col] = left[col] - {val}  # one-hot <= 0.5 -> value is NOT val
        right = {k: set(v) for k, v in allowed.items()}
        right[col] = right[col] & {val}
        walk(t.children_left[node], left)
        walk(t.children_right[node], right)

    walk(0, {k: set(v) for k, v in universe.items()})
    return pd.DataFrame(rows).sort_values("rate", ascending=False).reset_index(drop=True)


def fit_tree(f: pd.DataFrame, target: str, features: list[str], depth: int = 3, seed: int = 42):
    """Depth-limited tree; class weights balance the target, leaves report raw rates."""
    from sklearn.metrics import balanced_accuracy_score, roc_auc_score

    X = pd.get_dummies(f[features].astype(str), prefix_sep="=")
    y = f[target].astype(int).to_numpy()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=seed, stratify=y)
    model = DecisionTreeClassifier(
        max_depth=depth,
        min_samples_leaf=max(50, int(0.01 * len(X_tr))),
        class_weight="balanced",
        random_state=seed,
    )
    model.fit(X_tr, y_tr)
    leaves = model.apply(X)
    nodes = range(model.tree_.node_count)
    leaf_rate = pd.Series(y).groupby(leaves).mean().reindex(nodes).to_numpy()
    leaf_cases = pd.Series(leaves).value_counts().reindex(nodes).fillna(0).to_numpy()
    proba = model.predict_proba(X_te)[:, 1]
    metrics = {
        "balanced_accuracy_test": float(balanced_accuracy_score(y_te, model.predict(X_te))),
        "roc_auc_test": float(roc_auc_score(y_te, proba)),
        "train_cases": int(len(X_tr)),
        "test_cases": int(len(X_te)),
    }
    imp = (
        pd.Series(model.feature_importances_, index=X.columns)
        .groupby(lambda c: c.split("=")[0])
        .sum()
        .sort_values(ascending=False)
    )
    rules = tree_rules(model, list(X.columns), leaf_rate, leaf_cases, y.mean())
    return model, X, rules, imp, metrics


def plot_tree_png(model, X: pd.DataFrame, path, title: str) -> None:
    fig, ax = viz.plt.subplots(figsize=(15, 6.5))
    names = [c.replace("=", " = ") for c in X.columns]
    plot_tree(
        model,
        feature_names=names,
        class_names=["normal", "flagged"],
        filled=False,
        impurity=False,
        proportion=True,
        rounded=True,
        fontsize=8,
        ax=ax,
    )
    ax.set_title(title)
    viz.save(fig, path)


def plot_lifts(t: pd.DataFrame, path, title: str, k: int = 10) -> None:
    top = t.head(k)
    labels = [
        f"{a}: {v}" if v not in ("True",) else a
        for a, v in zip(top["attribute"], top["value"], strict=True)
    ]
    fig, ax = viz.plt.subplots(figsize=(9, 4.2))
    viz.hbar(ax, labels, top["lift"], fmt="×{:.2f}", color=viz.SERIES[1])
    ax.axvline(1, color=viz.INK_2, lw=1, ls="--")
    ax.xaxis.set_major_formatter(viz.matplotlib.ticker.StrMethodFormatter("{x:.1f}"))
    ax.set_xlabel("Lift (1.0 = average item)")
    ax.set_title(title)
    viz.save(fig, path)


def run(clean: pd.DataFrame, paths) -> dict:
    out = paths.results / "rootcause"
    out.mkdir(parents=True, exist_ok=True)
    f = build_features(clean)

    # Target A: slow = top quartile of cycle time among completed invoice items of the cohort.
    timed = f[
        (f["status"] == "complete") & f["in_cohort"] & f["item_category"].isin(C.INVOICE_CATEGORIES)
    ].copy()
    p75 = float(timed["cycle_days"].quantile(0.75))
    timed["slow"] = timed["cycle_days"] > p75
    # Target B: any compliance deviation, all completed items.
    comp = f[f["status"] == "complete"].copy()

    results = {"slow_threshold_days": p75, "slow_cases": int(len(timed))}
    for name, data, target, feats in [
        ("slow_order", timed, "slow", ORDER_FEATURES),
        ("slow_process", timed, "slow", PROCESS_FEATURES),
        ("deviation_order", comp, "any_deviation", ORDER_FEATURES),
    ]:
        lifts, base = lift_table(data, target, feats)
        lifts.to_csv(out / f"lift_{name}.csv", index=False, float_format="%.4f")
        model, X, rules, imp, metrics = fit_tree(data, target, feats)
        rules.to_csv(out / f"tree_rules_{name}.csv", index=False, float_format="%.4f")
        plot_tree_png(model, X, paths.figures / f"tree_{name}.png", f"Decision tree · {name}")
        plot_lifts(
            lifts,
            paths.figures / f"lift_{name}.png",
            {
                "slow_order": "What raises the odds of a slow item (known at order time)",
                "slow_process": "What happens to slow items (process behaviour)",
                "deviation_order": "What raises the odds of a compliance deviation",
            }[name],
        )
        results[name] = {
            "base_rate": float(base),
            "cases": int(len(data)),
            "metrics": metrics,
            "importance": imp.head(6).round(4).to_dict(),
            "top_lifts": lifts.head(8).to_dict("records"),
            "top_rules": rules.head(4).to_dict("records"),
            "bottom_rules": rules.tail(2).to_dict("records"),
        }
    # Combined effect of process behaviours: median cycle with none vs with each.
    clean_mask = ~timed[PROCESS_FEATURES].any(axis=1)
    results["median_no_behaviour"] = float(timed.loc[clean_mask, "cycle_days"].median())
    results["share_no_behaviour"] = float(clean_mask.mean())
    results["behaviour_medians"] = {
        k: {
            "share": float(timed[k].mean()),
            "median_days": float(timed.loc[timed[k], "cycle_days"].median()),
        }
        for k in PROCESS_FEATURES
        if timed[k].sum() >= 30
    }
    # Hotspot: the tree's slowest order-time segment, profiled against everything else.
    hot = (timed["vendor_size"] == "top (>5k items)") & timed["po_value_band"].str.match("Q[12]")
    prof = {}
    for nm, m in [("hotspot", hot), ("rest", ~hot)]:
        g = timed[m]
        prof[nm] = {
            "cases": int(len(g)),
            "vendors": int(clean.loc[clean["case_id"].isin(g.index), "vendor"].nunique()),
            "median_cycle_days": float(g["cycle_days"].median()),
            "median_po_to_gr_days": float(g["po_to_gr_days"].median()),
            "median_match_to_clear_days": float(g["match_to_clear_days"].median()),
            "payment_block_share": float(g["payment_block"].mean()),
            "slow_share": float(g["slow"].mean()),
            "spend_area_top": g["spend_area"]
            .value_counts(normalize=True)
            .head(3)
            .round(3)
            .to_dict(),
        }
    results["hotspot_profile"] = prof
    (out / "rootcause_summary.json").write_text(json.dumps(results, indent=2, default=str))
    return results
