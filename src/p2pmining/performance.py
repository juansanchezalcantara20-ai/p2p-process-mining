"""Phase 3 - performance and bottlenecks.

Cycle-time distribution, waiting time between activities, where waiting accumulates, and how
it varies by item category, spend area, vendor and document type. Only complete cases are
measured (see quality.case_status): an open case has no end, so including it would bias
cycle time downwards.

Medians and percentiles are used throughout because P2P durations are heavily right-skewed:
a handful of items that wait a year pull the mean far away from what a typical item
experiences. The mean is reported next to the median to make that gap visible.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from . import viz
from .discovery import dfg_table

INVOICE_END = C.CLEAR


def case_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per case with milestones, cycle time and descriptive attributes."""
    a, ts = df["activity"], df["timestamp"]

    def first(act):
        return ts.where(a == act)

    m = pd.DataFrame(
        {
            "case_id": df["case_id"],
            "po": first(C.PO),
            "pr": first(C.PR),
            "gr": first(C.GR),
            "vci": first(C.VCI),
            "ir": first(C.IR),
            "clear_last": first(C.CLEAR),
            "clear": first(C.CLEAR),
            "gr_last": first(C.GR),
            "block": first(C.REMOVE_BLOCK),
            "ts": ts,
            "value": df["net_worth_eur"].where(a == C.PO),
        }
    )
    g = m.groupby("case_id", sort=False)
    out = g.agg(
        po=("po", "min"),
        pr=("pr", "min"),
        gr=("gr", "min"),
        gr_last=("gr_last", "max"),
        vci=("vci", "min"),
        ir=("ir", "min"),
        clear=("clear", "min"),
        clear_last=("clear_last", "max"),
        block=("block", "min"),
        start=("ts", "min"),
        end=("ts", "max"),
        value=("value", "max"),
    )
    attrs = [
        c
        for c in [
            "item_category",
            "spend_area",
            "sub_spend_area",
            "vendor",
            "document_type",
            "item_type",
            "company",
            "status",
        ]
        if c in df.columns
    ]
    out = out.join(df.groupby("case_id", sort=False)[attrs].first())
    out["n_events"] = g.size()
    out["spend_area"] = out["spend_area"].fillna("Unknown")
    is_cons = out["item_category"] == C.CAT_CONSIGNMENT
    out["end_milestone"] = np.where(is_cons, out["gr_last"], out["clear_last"])
    out["end_milestone"] = pd.to_datetime(out["end_milestone"])
    days = lambda x: x.dt.total_seconds() / 86400  # noqa: E731
    out["cycle_days"] = days(out["end_milestone"] - out["po"])
    out["po_to_gr_days"] = days(out["gr"] - out["po"])
    out["invoice_capture_days"] = days(out["ir"] - out["vci"])
    matched = out[["gr", "ir"]].max(axis=1)
    out["match_to_clear_days"] = days(out["clear"] - matched)
    out["po_month"] = out["po"].dt.to_period("M").astype(str)
    return out


def describe(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {"n": 0}
    q = s.quantile([0.25, 0.5, 0.75, 0.9, 0.95])
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(q[0.5]),
        "p25": float(q[0.25]),
        "p75": float(q[0.75]),
        "p90": float(q[0.9]),
        "p95": float(q[0.95]),
        "max": float(s.max()),
    }


def segment(ct: pd.DataFrame, by: str, top: int | None = None, min_cases: int = 30) -> pd.DataFrame:
    g = ct.groupby(by)["cycle_days"]
    t = pd.DataFrame(
        {
            "cases": g.size(),
            "median_days": g.median(),
            "p75_days": g.quantile(0.75),
            "p90_days": g.quantile(0.9),
            "mean_days": g.mean(),
            "total_case_days": g.sum(),
        }
    )
    t = t[t["cases"] >= min_cases].sort_values("cases", ascending=False)
    if top:
        t = t.head(top)
    return t.reset_index()


def plot_cycle_distribution(ct: pd.DataFrame, figures) -> None:
    inv = ct[ct["item_category"].isin(C.INVOICE_CATEGORIES)]["cycle_days"].clip(lower=0.5)
    fig, ax = viz.plt.subplots(figsize=(8, 3.8))
    bins = np.logspace(np.log10(0.5), np.log10(inv.max() + 1), 60)
    ax.hist(inv, bins=bins, color=viz.SERIES[0], edgecolor=viz.SURFACE, linewidth=0.5)
    ax.set_xscale("log")
    for q, lab in [(inv.median(), "median"), (inv.mean(), "mean"), (inv.quantile(0.9), "P90")]:
        ax.axvline(q, color=viz.INK_2 if lab != "mean" else viz.SERIES[1], lw=1.2, ls="--")
        ax.text(q, ax.get_ylim()[1] * 0.92, f" {lab}\n {q:.0f} d", fontsize=8.5, color=viz.INK)
    ax.set_xlabel("PO creation → last invoice cleared (days, log scale)")
    ax.set_ylabel("Cases")
    ax.set_title("End-to-end cycle time, invoice items (POs created Jan-Aug 2018)")
    ax.yaxis.set_major_formatter(viz.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    viz.save(fig, figures / "cycle_time_distribution.png")


def plot_censoring(by_month: pd.DataFrame, figures) -> None:
    t = by_month[by_month["cases"] >= 100]
    fig, ax = viz.plt.subplots(figsize=(8, 3.4))
    in_c = (t["po_month"] >= C.COHORT_START[:7]) & (t["po_month"] < C.COHORT_END[:7])
    colors = [viz.SERIES[0] if c else viz.MUTED for c in in_c]
    ax.bar(t["po_month"], t["median_days"], color=colors, width=0.62, edgecolor=viz.SURFACE)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Median cycle time of\nfinished items (days)")
    ax.set_title("Late cohorts look fast only because their slow items have not finished yet")
    ax.tick_params(axis="x", rotation=45)
    ax.text(
        len(t) - 0.5,
        t["median_days"].max() * 0.95,
        "grey = excluded\n(right-censored)",
        ha="right",
        va="top",
        fontsize=8.5,
        color=viz.INK_2,
    )
    viz.save(fig, figures / "censoring_by_month.png")


def plot_range(t: pd.DataFrame, label_col: str, title: str, path, color=viz.SERIES[0]) -> None:
    """Dot = median, bar = P25-P90 range: shows typical case and tail at once."""
    if t.empty:
        return
    t = t.copy().iloc[::-1]
    g = t[label_col].astype(str)
    fig, ax = viz.plt.subplots(figsize=(8.5, 0.42 * len(t) + 1.4))
    y = np.arange(len(t))
    p25 = t["p25_days"] if "p25_days" in t else t["median_days"]
    ax.hlines(y, p25, t["p90_days"], color=color, alpha=0.35, lw=6)
    ax.plot(t["median_days"], y, "o", color=color, ms=8, mec=viz.SURFACE, mew=2)
    for yi, (med, p90, n_) in enumerate(
        zip(t["median_days"], t["p90_days"], t["cases"], strict=True)
    ):
        ax.text(
            p90 + 2, yi, f"median {med:.0f} d · n={n_:,}", va="center", fontsize=8, color=viz.INK_2
        )
    ax.set_yticks(y, g)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, t["p90_days"].max() * 1.45)
    ax.set_xlabel("Cycle time, days (dot = median, bar = P25 to P90)")
    ax.set_title(title)
    viz.save(fig, path)


def plot_waiting_pareto(edges: pd.DataFrame, figures, k: int = 10) -> None:
    top = edges.sort_values("total_days", ascending=False).head(k)
    share = top["total_days"] / edges["total_days"].sum()
    abbrev = {
        C.PO: "PO",
        C.GR: "GR",
        C.IR: "IR",
        C.VCI: "Vendor invoice",
        C.CLEAR: "Clear",
        C.REMOVE_BLOCK: "Remove block",
        C.PR: "PR",
        "Receive Order Confirmation": "Order conf.",
        C.SES: "Service entry",
        C.CHANGE_QTY: "Change qty",
        C.CHANGE_PRICE: "Change price",
    }
    labels = [
        f"{abbrev.get(s, s)} → {abbrev.get(t, t)}"
        for s, t in zip(top["source"], top["target"], strict=True)
    ]
    fig, ax = viz.plt.subplots(figsize=(8.5, 4.2))
    viz.hbar(ax, labels, 100 * share, fmt="{:.1f}%")
    ax.xaxis.set_major_formatter(viz.matplotlib.ticker.StrMethodFormatter("{x:.0f}"))
    ax.set_xlabel("Share of all waiting time in completed cases (%)")
    ax.set_title("Where waiting accumulates (top 10 hand-overs)")
    viz.save(fig, figures / "waiting_pareto.png")


def plot_stages(stages: pd.DataFrame, figures) -> None:
    fig, ax = viz.plt.subplots(figsize=(8, 2.9))
    viz.hbar(ax, stages["stage"], stages["median_days"], fmt="{:.0f} d")
    ax.set_xlabel("Median days")
    ax.set_title("Median duration of each stage (completed invoice cases)")
    viz.save(fig, figures / "stage_durations.png")


def run(clean: pd.DataFrame, paths) -> dict:
    out = paths.results / "performance"
    out.mkdir(parents=True, exist_ok=True)
    complete_ids = clean.loc[clean["status"] == "complete", "case_id"].unique()
    df = clean[clean["case_id"].isin(complete_ids)]
    ct = case_table(df)
    ct = ct[ct["cycle_days"].notna() & (ct["cycle_days"] >= 0)]
    by_month_all = segment(
        ct[ct["item_category"].isin(C.INVOICE_CATEGORIES)], "po_month", min_cases=1
    ).sort_values("po_month")
    ct["in_cohort"] = (ct["po"] >= C.COHORT_START) & (ct["po"] < C.COHORT_END)
    ct.reset_index().to_parquet(C.DATA_INTERIM / "case_table.parquet", index=False) if (
        paths.root == C.ROOT
    ) else None
    ct_all = ct
    ct = ct[ct["in_cohort"]]
    inv = ct[ct["item_category"].isin(C.INVOICE_CATEGORIES)]

    edges = dfg_table(df[df["case_id"].isin(inv.index)])
    edges.to_csv(out / "waiting_by_handover.csv", index=False, float_format="%.3f")

    stages = pd.DataFrame(
        [
            ("PO → first goods receipt", inv["po_to_gr_days"]),
            ("Vendor invoice date → invoice posted", inv["invoice_capture_days"]),
            ("Goods + invoice matched → cleared", inv["match_to_clear_days"]),
            ("End to end (PO → last clear)", inv["cycle_days"]),
        ],
        columns=["stage", "values"],
    )
    stages["median_days"] = [v.dropna().median() for v in stages["values"]]
    stages["p90_days"] = [v.dropna().quantile(0.9) for v in stages["values"]]
    stages["mean_days"] = [v.dropna().mean() for v in stages["values"]]
    stages = stages.drop(columns="values")
    stages.to_csv(out / "stage_durations.csv", index=False, float_format="%.2f")

    by_cat = segment(ct, "item_category", min_cases=1)
    by_area = segment(inv, "spend_area", top=12)
    by_vendor = segment(inv, "vendor", top=15)
    by_doc = segment(inv, "document_type", min_cases=1)
    by_month = by_month_all
    for name, t in [
        ("by_item_category", by_cat),
        ("by_spend_area", by_area),
        ("by_vendor_top15", by_vendor),
        ("by_document_type", by_doc),
        ("by_po_month", by_month),
    ]:
        t.to_csv(out / f"cycle_{name}.csv", index=False, float_format="%.2f")

    for t in (by_cat, by_area, by_vendor):
        t["p25_days"] = np.nan
    by_cat["p25_days"] = (
        ct.groupby("item_category")["cycle_days"]
        .quantile(0.25)
        .reindex(by_cat["item_category"])
        .to_numpy()
    )
    by_area["p25_days"] = (
        inv.groupby("spend_area")["cycle_days"]
        .quantile(0.25)
        .reindex(by_area["spend_area"])
        .to_numpy()
    )
    by_vendor["p25_days"] = (
        inv.groupby("vendor")["cycle_days"].quantile(0.25).reindex(by_vendor["vendor"]).to_numpy()
    )

    plot_cycle_distribution(ct, paths.figures)
    plot_range(
        by_cat,
        "item_category",
        "Cycle time by item category",
        paths.figures / "cycle_by_category.png",
    )
    plot_range(
        by_area,
        "spend_area",
        "Cycle time by spend area (12 largest, invoice items)",
        paths.figures / "cycle_by_spend_area.png",
    )
    plot_range(
        by_vendor,
        "vendor",
        "Cycle time for the 15 largest vendors (invoice items)",
        paths.figures / "cycle_by_vendor.png",
    )
    plot_waiting_pareto(edges, paths.figures)
    plot_stages(stages, paths.figures)

    blocked = inv["block"].notna()
    total_wait = float(edges["total_days"].sum())
    top_edge = edges.sort_values("total_days", ascending=False).iloc[0]
    plot_censoring(by_month_all, paths.figures)
    summary = {
        "cohort": [C.COHORT_START, C.COHORT_END],
        "complete_cases_all": int(len(ct_all)),
        "complete_cases": int(len(ct)),
        "invoice_cases": int(len(inv)),
        "cycle_all": describe(ct["cycle_days"]),
        "cycle_invoice": describe(inv["cycle_days"]),
        "cycle_consignment": describe(
            ct.loc[ct["item_category"] == C.CAT_CONSIGNMENT, "cycle_days"]
        ),
        "stages": stages.to_dict("records"),
        "payment_block": {
            "share_cases": float(blocked.mean()),
            "median_with": float(inv.loc[blocked, "cycle_days"].median()),
            "median_without": float(inv.loc[~blocked, "cycle_days"].median()),
            "median_ir_to_clear_with": float(
                (inv.loc[blocked, "clear"] - inv.loc[blocked, "ir"]).dt.days.median()
            ),
            "median_ir_to_clear_without": float(
                (inv.loc[~blocked, "clear"] - inv.loc[~blocked, "ir"]).dt.days.median()
            ),
        },
        "top_waiting_handover": {
            "source": top_edge["source"],
            "target": top_edge["target"],
            "share_of_total_wait": float(top_edge["total_days"] / total_wait),
            "median_days": float(top_edge["median_days"]),
        },
        "top3_handover_share": float(edges["total_days"].nlargest(3).sum() / total_wait),
        "slowest_spend_area": by_area.sort_values("median_days")
        .iloc[-1][["spend_area", "median_days", "cases"]]
        .to_dict(),
        "fastest_spend_area": by_area.sort_values("median_days")
        .iloc[0][["spend_area", "median_days", "cases"]]
        .to_dict(),
        "vendor_median_range": [
            float(by_vendor["median_days"].min()),
            float(by_vendor["median_days"].max()),
        ],
    }
    (out / "performance_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
