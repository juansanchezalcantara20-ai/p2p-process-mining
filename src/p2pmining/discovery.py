"""Phase 2 - discover the AS-IS process from the data.

* directly-follows graph (DFG) with frequencies and with median waiting times;
* variant analysis: how many variants cover 80% of cases, happy path versus reality;
* Inductive Miner (infrequent) model exported to BPMN.

Cancelled cases (deleted PO items) are excluded; open cases are kept because they still show
how work flows.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd
from pm4py.util import constants as _pm_constants

from . import config as C
from . import viz

log = logging.getLogger(__name__)
_pm_constants.SHOW_PROGRESS_BAR = False

# Textbook flow, allowing optional requisition / order confirmation and either order of
# vendor-invoice date and goods receipt (both happen independently in reality).
_OPT = rf"(?:{re.escape(C.PR)} > )?{re.escape(C.PO)}(?: > Receive Order Confirmation)?"
_INV = (
    rf"(?:{re.escape(C.VCI)} > {re.escape(C.GR)}|{re.escape(C.GR)} > {re.escape(C.VCI)})"
    rf" > {re.escape(C.IR)} > {re.escape(C.CLEAR)}"
)
HAPPY_PATTERNS = {
    "invoice": re.compile(rf"^{_OPT} > {_INV}$"),
    "two_way": re.compile(
        rf"^{_OPT} > {re.escape(C.VCI)} > {re.escape(C.IR)} > {re.escape(C.CLEAR)}$"
    ),
    "consignment": re.compile(rf"^{_OPT} > {re.escape(C.GR)}$"),
}
STRICT_HAPPY = " > ".join([C.PO, C.VCI, C.GR, C.IR, C.CLEAR])


def is_happy(variant: str, category: str) -> bool:
    if category == C.CAT_CONSIGNMENT:
        return bool(HAPPY_PATTERNS["consignment"].match(variant))
    if category == C.CAT_2W:
        return bool(HAPPY_PATTERNS["two_way"].match(variant))
    return bool(HAPPY_PATTERNS["invoice"].match(variant))


def transitions(df: pd.DataFrame) -> pd.DataFrame:
    """One row per directly-follows pair inside a case, with the waiting time in days."""
    d = df[["case_id", "activity", "timestamp"]]
    nxt = d.groupby("case_id", sort=False).shift(-1)
    t = pd.DataFrame(
        {
            "case_id": d["case_id"],
            "source": d["activity"],
            "target": nxt["activity"],
            "wait_days": (nxt["timestamp"] - d["timestamp"]).dt.total_seconds() / 86400,
        }
    )
    return t[t["target"].notna()].reset_index(drop=True)


def dfg_table(df: pd.DataFrame) -> pd.DataFrame:
    t = transitions(df)
    g = t.groupby(["source", "target"])["wait_days"]
    out = pd.DataFrame(
        {
            "count": g.size(),
            "cases": t.groupby(["source", "target"])["case_id"].nunique(),
            "median_days": g.median(),
            "p90_days": g.quantile(0.9),
            "mean_days": g.mean(),
            "total_days": g.sum(),
        }
    ).reset_index()
    return out.sort_values("count", ascending=False).reset_index(drop=True)


def variant_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return (variants with counts and coverage, case -> variant mapping)."""
    seq = df.groupby("case_id", sort=False)["activity"].agg(" > ".join)
    cat = df.groupby("case_id", sort=False)["item_category"].first()
    vc = seq.value_counts()
    vt = pd.DataFrame({"variant": vc.index, "cases": vc.to_numpy()})
    vt["share"] = vt["cases"] / vt["cases"].sum()
    vt["cumulative_share"] = vt["share"].cumsum()
    vt["n_events"] = vt["variant"].str.count(" > ") + 1
    main_cat = (
        pd.DataFrame({"variant": seq, "cat": cat})
        .groupby("variant")["cat"]
        .agg(lambda s: s.value_counts().index[0])
    )
    vt["main_category"] = vt["variant"].map(main_cat)
    vt["happy_path"] = [
        is_happy(v, c) for v, c in zip(vt["variant"], vt["main_category"], strict=True)
    ]
    return vt, seq


def _filtered_dfg(edges: pd.DataFrame, df: pd.DataFrame, min_case_share: float):
    n_cases = df["case_id"].nunique()
    act_cases = df.groupby("activity")["case_id"].nunique()
    keep_acts = set(act_cases[act_cases >= min_case_share * n_cases].index)
    e = edges[
        edges["source"].isin(keep_acts)
        & edges["target"].isin(keep_acts)
        & (edges["cases"] >= min_case_share * n_cases)
    ]
    keep_acts = set(e["source"]) | set(e["target"])
    firsts = df.groupby("case_id", sort=False)["activity"].first().value_counts()
    lasts = df.groupby("case_id", sort=False)["activity"].last().value_counts()
    start = {a: int(c) for a, c in firsts.items() if a in keep_acts and c >= 0.005 * n_cases}
    end = {a: int(c) for a, c in lasts.items() if a in keep_acts and c >= 0.005 * n_cases}
    return e, start, end


def render_dfgs(edges: pd.DataFrame, df: pd.DataFrame, figures, min_case_share=0.02) -> None:
    import pm4py

    e, start, end = _filtered_dfg(edges, df, min_case_share)
    freq = {(r.source, r.target): int(r.count) for r in e.itertuples()}
    perf = {(r.source, r.target): float(r.median_days) * 86400 for r in e.itertuples()}
    pm4py.save_vis_dfg(freq, start, end, str(figures / "dfg_frequency.png"))
    pm4py.save_vis_performance_dfg(
        perf, start, end, str(figures / "dfg_performance.png"), aggregation_measure="median"
    )


def plot_variant_coverage(vt: pd.DataFrame, figures) -> None:
    fig, ax = viz.plt.subplots(figsize=(8, 3.6))
    k = min(len(vt), 400)
    ax.plot(np.arange(1, k + 1), 100 * vt["cumulative_share"].iloc[:k], color=viz.SERIES[0])
    n80 = int((vt["cumulative_share"] < 0.8).sum() + 1)
    ax.axhline(80, color=viz.MUTED, lw=1, ls="--")
    ax.axvline(n80, color=viz.MUTED, lw=1, ls="--")
    ax.annotate(
        f"{n80} variants cover 80% of cases\n(out of {len(vt):,})",
        (n80, 80),
        xytext=(n80 + k * 0.08, 55),
        fontsize=9,
        color=viz.INK,
        arrowprops={"arrowstyle": "-", "color": viz.INK_2, "lw": 0.8},
    )
    ax.set_xscale("log")
    ax.set_ylim(0, 100)
    ax.set_xlabel("Number of most-frequent variants (log scale)")
    ax.set_ylabel("Cases covered (%)")
    ax.set_title("A few variants carry most cases; a long tail carries the rest")
    viz.save(fig, figures / "variant_coverage.png")


def _pm4py_log(df: pd.DataFrame) -> pd.DataFrame:
    import pm4py

    return pm4py.format_dataframe(
        df[["case_id", "activity", "timestamp"]].copy(),
        case_id="case_id",
        activity_key="activity",
        timestamp_key="timestamp",
    )


def discover_model(
    df: pd.DataFrame, paths, min_activity_share: float = 0.05, noise: float = 0.2, tag: str = "core"
) -> dict:
    """Inductive Miner (infrequent) -> process tree -> BPMN + Petri net, with quality metrics.

    ``min_activity_share`` keeps only activities that occur in at least that share of cases;
    rare activities are what turns a model into spaghetti (see DECISIONS.md, D-P2).
    """
    import pm4py

    n_cases = df["case_id"].nunique()
    act_share = df.groupby("activity")["case_id"].nunique() / n_cases
    core = sorted(act_share[act_share >= min_activity_share].index)
    log_df = _pm4py_log(df[df["activity"].isin(core)])
    tree = pm4py.discover_process_tree_inductive(log_df, noise_threshold=noise)
    bpmn = pm4py.convert_to_bpmn(tree)
    pm4py.write_bpmn(bpmn, str(paths.models / f"as_is_inductive_{tag}.bpmn"))
    pm4py.save_vis_bpmn(bpmn, str(paths.figures / f"as_is_bpmn_{tag}.png"))
    net, im, fm = pm4py.convert_to_petri_net(tree)
    pm4py.write_pnml(net, im, fm, str(paths.models / f"as_is_inductive_{tag}.pnml"))
    (paths.models / f"as_is_process_tree_{tag}.txt").write_text(str(tree) + "\n")
    fit = pm4py.fitness_token_based_replay(log_df, net, im, fm)
    # Precision on a fixed random subset of cases keeps runtime bounded on the full log.
    rng = np.random.default_rng(42)
    ids = log_df["case:concept:name"].unique()
    sub = log_df[log_df["case:concept:name"].isin(rng.choice(ids, min(len(ids), 5000), False))]
    prec = pm4py.precision_token_based_replay(sub, net, im, fm)
    return {
        "min_activity_share": min_activity_share,
        "activities_in_model": core,
        "events_kept_share": float(df["activity"].isin(core).mean()),
        "noise_threshold": noise,
        "process_tree": str(tree),
        "log_fitness": float(fit["log_fitness"]),
        "fitting_traces_pct": float(fit["perc_fit_traces"]),
        "precision_5000_cases": float(prec),
    }


def plot_top_variants(vt: pd.DataFrame, figures, k: int = 10) -> None:
    top = vt.head(k).copy()
    abbrev = {
        C.PR: "PR",
        C.PO: "PO",
        C.VCI: "VendorInv",
        C.GR: "GR",
        C.IR: "IR",
        C.CLEAR: "Clear",
        C.REMOVE_BLOCK: "RemoveBlock",
        "Receive Order Confirmation": "OrderConf",
        C.SES: "ServiceEntry",
        C.CHANGE_APPROVAL: "ChangeApproval",
    }

    def short(v: str) -> str:
        return " → ".join(abbrev.get(a, a) for a in v.split(" > "))

    labels = [f"{short(v)}" for v in top["variant"]]
    fig, ax = viz.plt.subplots(figsize=(10, 4.6))
    viz.hbar(
        ax,
        labels,
        100 * top["share"],
        fmt="{:.1f}%",
        highlight=top["happy_path"].tolist(),
    )
    ax.set_title("Top 10 variants (blue = textbook path; grey = deviation or unfinished)")
    ax.set_xlabel("Share of cases (%)")
    ax.xaxis.set_major_formatter(viz.matplotlib.ticker.StrMethodFormatter("{x:.0f}"))
    viz.save(fig, figures / "top_variants.png")


def run(clean: pd.DataFrame, paths) -> dict:
    out = paths.results / "discovery"
    out.mkdir(parents=True, exist_ok=True)
    df = clean[clean["status"] != "cancelled"]

    edges = dfg_table(df)
    edges.to_csv(out / "dfg_edges.csv", index=False, float_format="%.3f")
    render_dfgs(edges, df, paths.figures)

    vt, seq = variant_table(df)
    vt.head(50).to_csv(out / "top_variants.csv", index=False, float_format="%.4f")
    plot_variant_coverage(vt, paths.figures)
    plot_top_variants(vt, paths.figures)

    status = df.drop_duplicates("case_id").set_index("case_id")["status"]
    cat = df.drop_duplicates("case_id").set_index("case_id")["item_category"]
    happy_case = pd.Series(
        [is_happy(v, c) for v, c in zip(seq, cat.reindex(seq.index), strict=True)], index=seq.index
    )
    complete = status.reindex(seq.index) == "complete"
    by_cat = (
        pd.DataFrame({"cat": cat.reindex(seq.index), "happy": happy_case, "complete": complete})
        .loc[complete]
        .groupby("cat")["happy"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "happy_share", "size": "complete_cases"})
    )
    n80 = int((vt["cumulative_share"] < 0.8).sum() + 1)
    model = discover_model(df, paths, min_activity_share=0.05, tag="core")
    model_all = discover_model(df, paths, min_activity_share=0.0, tag="all_activities")
    model_all.pop("activities_in_model")
    summary = {
        "cases": int(df["case_id"].nunique()),
        "events": int(len(df)),
        "activities": int(df["activity"].nunique()),
        "variants": int(len(vt)),
        "variants_for_80pct": n80,
        "singleton_variants": int((vt["cases"] == 1).sum()),
        "top_variant": vt.iloc[0]["variant"],
        "top_variant_share": float(vt.iloc[0]["share"]),
        "strict_happy_path": STRICT_HAPPY,
        "strict_happy_share": float(vt.loc[vt["variant"] == STRICT_HAPPY, "share"].sum()),
        "textbook_share_all_cases": float(happy_case.mean()),
        "textbook_share_complete_cases": float(happy_case[complete].mean()),
        "textbook_share_by_category_complete": by_cat.reset_index().to_dict("records"),
        "dfg_edges": int(len(edges)),
        "model": model,
        "model_all_activities": model_all,
    }
    viz_json = out / "discovery_summary.json"
    import json

    viz_json.write_text(json.dumps(summary, indent=2, default=str))
    return summary
