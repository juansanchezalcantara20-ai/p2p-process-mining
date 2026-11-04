"""Phase 4 - compliance and conformance checking.

Two complementary lenses:

1. **Business rules** typical of purchase-to-pay controls, evaluated case by case:
   three-way match before payment, invoice before goods receipt, price/quantity changes after
   the PO, payment blocks, after-the-fact purchasing (invoice dated before the PO), and
   approval changes after goods have been received.
2. **Model-based conformance**: token-based replay of every case against a normative
   (expected) model per item category, plus alignments on a fixed random subset to locate
   where cases deviate.

Deviations are ranked by impact: cases affected, euro value affected and excess cycle time
relative to comparable conforming cases.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from pm4py.util import constants as _pm_constants

from . import config as C
from . import viz

_pm_constants.SHOW_PROGRESS_BAR = False

RULES = {
    "R1_no_three_way_match": {
        "title": "Paid without a three-way match",
        "control": "An item requiring 3-way match is cleared only after both a goods receipt "
        "and an invoice receipt exist.",
        "applies_to": "3-way match items that reached Clear Invoice",
    },
    "R2_invoice_before_gr": {
        "title": "Invoice posted before goods receipt (GR-based IV)",
        "control": "Items flagged 'invoice after GR' must not have the invoice posted before "
        "the goods are received.",
        "applies_to": "3-way match, invoice after GR",
    },
    "R3_price_change_after_po": {
        "title": "Price changed after the PO was issued",
        "control": "Prices are agreed before ordering; a change after the PO is rework.",
        "applies_to": "all items",
    },
    "R4_quantity_change_after_po": {
        "title": "Quantity changed after the PO was issued",
        "control": "Quantities are agreed before ordering; a change after the PO is rework.",
        "applies_to": "all items",
    },
    "R5_payment_block": {
        "title": "Invoice payment was blocked",
        "control": "A matched invoice flows to payment without manual block/release.",
        "applies_to": "invoice items",
    },
    "R6_after_the_fact_po": {
        "title": "Purchase without a prior PO (invoice dated before the PO)",
        "control": "No purchase without a purchase order: the vendor invoice date must not "
        "precede PO creation.",
        "applies_to": "invoice items",
    },
    "R7_invoice_cancelled": {
        "title": "Invoice receipt cancelled and re-posted",
        "control": "An invoice is posted once, correctly.",
        "applies_to": "invoice items",
    },
}


def rule_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Evaluate each rule per case. Returns a boolean violation matrix (NaN = not applicable)."""
    a, ts, cid = df["activity"], df["timestamp"], df["case_id"]

    def first(act):
        return ts.where(a == act)

    m = pd.DataFrame(
        {
            "case_id": cid,
            "po": first(C.PO),
            "gr": first(C.GR),
            "ir": first(C.IR),
            "vci": first(C.VCI),
            "clear": first(C.CLEAR),
            "price_chg": first(C.CHANGE_PRICE),
            "qty_chg": first(C.CHANGE_QTY),
            "block": (a == C.REMOVE_BLOCK) | (a == C.SET_BLOCK),
            "cancel_ir": a == "Cancel Invoice Receipt",
        }
    )
    g = m.groupby("case_id", sort=False).agg(
        po=("po", "min"),
        gr=("gr", "min"),
        ir=("ir", "min"),
        vci=("vci", "min"),
        clear=("clear", "min"),
        price_last=("price_chg", "max"),
        qty_last=("qty_chg", "max"),
        block=("block", "any"),
        cancel_ir=("cancel_ir", "any"),
    )
    cat = df.groupby("case_id", sort=False)["item_category"].first()
    three_way = cat.isin([C.CAT_3W_AFTER, C.CAT_3W_BEFORE])
    invoice = cat.isin(C.INVOICE_CATEGORIES)

    out = pd.DataFrame(index=g.index)
    paid = g["clear"].notna()
    r1 = paid & (g["gr"].isna() | g["ir"].isna() | (g["clear"] < g[["gr", "ir"]].max(axis=1)))
    out["R1_no_three_way_match"] = r1.where(three_way & paid)
    r2 = g["ir"].notna() & (g["gr"].isna() | (g["ir"] < g["gr"]))
    out["R2_invoice_before_gr"] = r2.where(cat == C.CAT_3W_AFTER)
    out["R3_price_change_after_po"] = g["price_last"].notna() & (g["price_last"] > g["po"])
    out["R4_quantity_change_after_po"] = g["qty_last"].notna() & (g["qty_last"] > g["po"])
    out["R5_payment_block"] = g["block"].where(invoice)
    out["R6_after_the_fact_po"] = (g["vci"].notna() & (g["vci"] < g["po"].dt.floor("D"))).where(
        invoice
    )
    out["R7_invoice_cancelled"] = g["cancel_ir"].where(invoice)
    return out


# --------------------------------------------------------------------------------------------
# Normative models (process-tree notation). Optional steps use X(..., tau); repetition for
# partial deliveries / invoices uses the loop operator *( body, tau ).
_PO_BLOCK = f"->( X( '{C.PR}', tau ), '{C.PO}', X( 'Receive Order Confirmation', tau ) )"
NORMATIVE = {
    # goods first, then invoice posting, then clearing - repeated per delivery
    C.CAT_3W_AFTER: f"->( {_PO_BLOCK}, *( ->( +( '{C.GR}', X( '{C.VCI}', tau ) ), '{C.IR}', "
    f"'{C.CLEAR}' ), tau ) )",
    # invoice may be posted before goods arrive, but clearing waits for both
    C.CAT_3W_BEFORE: f"->( {_PO_BLOCK}, *( ->( +( '{C.GR}', ->( X( '{C.VCI}', tau ), '{C.IR}' ) "
    f"), '{C.CLEAR}' ), tau ) )",
    C.CAT_2W: f"->( {_PO_BLOCK}, *( ->( X( '{C.VCI}', tau ), '{C.IR}', '{C.CLEAR}' ), tau ) )",
    C.CAT_CONSIGNMENT: f"->( {_PO_BLOCK}, *( '{C.GR}', tau ) )",
}


def normative_net(category: str):
    import pm4py
    from pm4py.objects.process_tree.utils.generic import parse

    tree = parse(NORMATIVE[category])
    return tree, *pm4py.convert_to_petri_net(tree)


def export_normative_models(paths) -> None:
    import pm4py

    for cat in C.ITEM_CATEGORIES:
        tree, *_ = normative_net(cat)
        slug = cat.lower().replace(",", "").replace(" ", "_").replace("-", "")
        bpmn = pm4py.convert_to_bpmn(tree)
        pm4py.write_bpmn(bpmn, str(paths.models / f"normative_{slug}.bpmn"))
        if cat == C.CAT_3W_BEFORE:
            pm4py.save_vis_bpmn(bpmn, str(paths.figures / "normative_3way_before_gr.png"))


def token_replay(df: pd.DataFrame) -> pd.DataFrame:
    """Token-based replay of every case against its category's normative model.

    Activities that are not in the normative model (price changes, payment blocks, ...) count
    as deviations, so a case 'fits' only if it follows the expected flow with nothing extra.
    """
    import pm4py
    from pm4py.algo.conformance.tokenreplay import algorithm as tbr

    rows = []
    for cat in C.ITEM_CATEGORIES:
        sub = df[df["item_category"] == cat]
        if sub.empty:
            continue
        _, net, im, fm = normative_net(cat)
        log_df = pm4py.format_dataframe(
            sub[["case_id", "activity", "timestamp"]].copy(),
            case_id="case_id",
            activity_key="activity",
            timestamp_key="timestamp",
        )
        params = {
            tbr.Variants.TOKEN_REPLAY.value.Parameters.CONSIDER_REMAINING_IN_FITNESS: True,
            tbr.Variants.TOKEN_REPLAY.value.Parameters.ENABLE_PLTR_FITNESS: False,
        }
        # replay unique variants, then map back to cases
        seq = log_df.groupby("case:concept:name", sort=False)["concept:name"].agg("\x1f".join)
        variants = [tuple(v.split("\x1f")) for v in pd.unique(seq.to_numpy())]
        vlog = pd.DataFrame(
            [
                {
                    "case:concept:name": f"v{i}",
                    "concept:name": act,
                    "time:timestamp": pd.Timestamp("2018-01-01") + pd.Timedelta(minutes=j),
                }
                for i, v in enumerate(variants)
                for j, act in enumerate(v)
            ]
        )
        res = tbr.apply(pm4py.convert_to_event_log(vlog), net, im, fm, parameters=params)
        model_acts = {t.label for t in net.transitions if t.label}
        vres = {}
        for v, r in zip(variants, res, strict=True):
            unknown = any(x not in model_acts for x in v)
            vres["\x1f".join(v)] = (r["trace_is_fit"] and not unknown, r["trace_fitness"], unknown)
        for case, v in seq.items():
            fit, fitness, unknown = vres[v]
            rows.append((case, cat, fit, fitness, unknown))
    return pd.DataFrame(
        rows, columns=["case_id", "item_category", "fits", "trace_fitness", "extra_activities"]
    ).set_index("case_id")


def alignment_deviations(df: pd.DataFrame, n_cases: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Optimal alignments on a fixed random subset; count log/model moves per activity."""
    import pm4py

    rng = np.random.default_rng(seed)
    counts: dict[tuple[str, str], int] = {}
    total = 0
    for cat in C.ITEM_CATEGORIES:
        ids = df.loc[df["item_category"] == cat, "case_id"].unique()
        if len(ids) == 0:
            continue
        k = max(1, int(round(n_cases * len(ids) / df["case_id"].nunique())))
        pick = rng.choice(ids, size=min(k, len(ids)), replace=False)
        sub = df[df["case_id"].isin(pick)]
        sub = sub[sub.groupby("case_id")["case_id"].transform("size") <= 60]
        _, net, im, fm = normative_net(cat)
        log_df = pm4py.format_dataframe(
            sub[["case_id", "activity", "timestamp"]].copy(),
            case_id="case_id",
            activity_key="activity",
            timestamp_key="timestamp",
        )
        aligned = pm4py.conformance_diagnostics_alignments(log_df, net, im, fm)
        for al in aligned:
            total += 1
            for log_mv, model_mv in al["alignment"]:
                if log_mv != ">>" and model_mv == ">>":
                    key = ("log move (extra, not in model)", log_mv)
                elif log_mv == ">>" and model_mv not in (None, ">>"):
                    key = ("model move (expected, missing)", model_mv)
                else:
                    continue
                counts[key] = counts.get(key, 0) + 1
    out = pd.DataFrame(
        [(k[0], k[1], v) for k, v in counts.items()], columns=["move_type", "activity", "moves"]
    )
    out["aligned_cases"] = total
    return out.sort_values("moves", ascending=False).reset_index(drop=True)


def impact_table(flags: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """Rank rules by cases, value and excess cycle time versus non-violating peers.

    Excess days compare medians within the same item category (so a rule that only applies to
    slow categories is not blamed for the category's own pace), then weight by violations.
    """
    rows = []
    timed = cases[cases["cycle_days"].notna()]
    for rule in flags.columns:
        f = flags[rule].dropna().astype(bool)
        n_app, n_viol = len(f), int(f.sum())
        value = float(cases.loc[f[f].index, "value"].sum())
        excess_total, excess_med = 0.0, np.nan
        t = timed.join(f.rename("viol"), how="inner")
        meds = []
        for _, g in t.groupby("item_category"):
            v, ok = g.loc[g["viol"], "cycle_days"], g.loc[~g["viol"], "cycle_days"]
            if len(v) >= 30 and len(ok) >= 30:
                d = v.median() - ok.median()
                excess_total += d * len(v)
                meds.append((d, len(v)))
        if meds:
            excess_med = sum(d * w for d, w in meds) / sum(w for _, w in meds)
        rows.append(
            {
                "rule": rule,
                "title": RULES[rule]["title"],
                "applicable_cases": n_app,
                "violating_cases": n_viol,
                "violation_rate": n_viol / n_app if n_app else np.nan,
                "value_eur": value,
                "excess_median_days": excess_med,
                "excess_case_days": excess_total,
            }
        )
    t = pd.DataFrame(rows)
    # Impact score: rank-average of the three impact dimensions (scale-free, no hidden weights).
    t["impact_rank"] = (
        t[["violating_cases", "value_eur", "excess_case_days"]]
        .fillna(0)
        .rank(ascending=False)
        .mean(axis=1)
    )
    return t.sort_values("impact_rank").reset_index(drop=True)


def plot_rules(t: pd.DataFrame, figures) -> None:
    fig, ax = viz.plt.subplots(figsize=(8.5, 3.8))
    viz.hbar(ax, t["title"], 100 * t["violation_rate"], fmt="{:.1f}%", color=viz.SERIES[1])
    ax.xaxis.set_major_formatter(viz.matplotlib.ticker.StrMethodFormatter("{x:.0f}"))
    ax.set_xlabel("Violation rate among applicable cases (%)")
    ax.set_title("Compliance rules: how often each control is breached")
    viz.save(fig, figures / "compliance_rules.png")


def plot_fitness(tr: pd.DataFrame, figures) -> None:
    g = tr.groupby("item_category")["fits"].mean().reindex(C.ITEM_CATEGORIES).dropna()
    fig, ax = viz.plt.subplots(figsize=(8, 2.8))
    viz.hbar(ax, g.index, 100 * g.to_numpy(), fmt="{:.1f}%")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Cases that conform to the normative model (%)")
    ax.set_title("Conformance by item category (completed cases, token replay)")
    viz.save(fig, figures / "conformance_by_category.png")


def run(clean: pd.DataFrame, paths) -> dict:
    from .performance import case_table

    out = paths.results / "conformance"
    out.mkdir(parents=True, exist_ok=True)
    df = clean[clean["status"] != "cancelled"]

    flags = rule_flags(df)
    ct = case_table(df)
    timed = ct.copy()
    in_cohort = (timed["po"] >= C.COHORT_START) & (timed["po"] < C.COHORT_END)
    timed.loc[(timed["status"] != "complete") | ~in_cohort, "cycle_days"] = np.nan
    impact = impact_table(flags, timed)
    impact.to_csv(out / "rule_impact.csv", index=False, float_format="%.4f")
    plot_rules(impact.sort_values("violation_rate", ascending=False), paths.figures)

    export_normative_models(paths)
    tr = token_replay(df)
    tr.join(flags).to_parquet(
        C.DATA_INTERIM / "conformance_cases.parquet"
    ) if paths.root == C.ROOT else None
    status_ = df.drop_duplicates("case_id").set_index("case_id")["status"]
    plot_fitness(tr[status_.reindex(tr.index).eq("complete").to_numpy()], paths.figures)
    al = alignment_deviations(df)
    al.head(20).to_csv(out / "alignment_deviations.csv", index=False)

    any_violation = flags.fillna(False).astype(bool).any(axis=1)
    status = df.drop_duplicates("case_id").set_index("case_id")["status"]
    tr["complete"] = status.reindex(tr.index).eq("complete").to_numpy()
    trc = tr[tr["complete"]]
    by_cat = trc.groupby("item_category").agg(
        cases=("fits", "size"), conforming=("fits", "mean"), mean_fitness=("trace_fitness", "mean")
    )
    summary = {
        "cases": int(len(tr)),
        "conforming_share_all": float(tr["fits"].mean()),
        "complete_cases": int(len(trc)),
        "conforming_share": float(trc["fits"].mean()),
        "mean_trace_fitness": float(trc["trace_fitness"].mean()),
        "share_with_extra_activities": float(trc["extra_activities"].mean()),
        "by_category": by_cat.reset_index().to_dict("records"),
        "any_rule_violation_share": float(any_violation.mean()),
        "rules": {k: v for k, v in RULES.items()},
        "impact": impact.to_dict("records"),
        "alignment_cases": int(al["aligned_cases"].iloc[0]) if len(al) else 0,
    }
    (out / "conformance_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
