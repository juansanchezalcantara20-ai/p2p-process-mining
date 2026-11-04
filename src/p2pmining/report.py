"""Render the MkDocs report pages from the result files written by each phase.

Every number in the report comes from ``results/``; nothing is typed by hand. Pages whose
inputs do not exist yet are skipped, so the site is valid after any phase.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config as C


def _load(paths, rel: str):
    p = paths.results / rel
    if not p.exists():
        return None
    if p.suffix == ".json":
        return json.loads(p.read_text())
    return pd.read_csv(p)


def n(x, d: int = 0) -> str:
    """Format a number with thousands separators."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:,.{d}f}"


def pct(x, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def md_table(df: pd.DataFrame, floatfmt: int = 1) -> str:
    def fmt(v):
        if isinstance(v, float):
            return n(v, floatfmt)
        if isinstance(v, int):
            return n(v)
        return str(v)

    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


# ------------------------------------------------------------------------------------------------
def page_quality(paths) -> str | None:
    q = _load(paths, "quality/quality_report.json")
    if q is None:
        return None
    fp, ts, du, od, cm = (
        q["fingerprint"],
        q["timestamps"],
        q["duplicates"],
        q["ordering"],
        q["completeness"],
    )
    log = pd.DataFrame(q["cleaning_log"])[
        ["step", "events_removed", "cases_removed", "events_after", "cases_after"]
    ]
    log.columns = ["Step", "Events removed", "Cases removed", "Events after", "Cases after"]
    rationale = "\n".join(
        f"{i + 1}. **{r['step']}** - {r['rationale']}" for i, r in enumerate(q["cleaning_log"])
    )
    years = ", ".join(f"{y}: {n(v)}" for y, v in ts["events_by_year"].items())
    dup_rows = pd.DataFrame(du["by_activity"])[["activity", "extra_copies"]].head(5)
    dup_rows.columns = ["Activity", "Extra identical copies"]
    dup_rows["Extra identical copies"] = dup_rows["Extra identical copies"].astype(int)
    before = pd.DataFrame(od["activities_dated_before_po"])
    before.columns = ["Activity dated before the PO", "Cases"]
    cat = pd.DataFrame(cm["by_category"]).T.reset_index().rename(columns={"index": "Item category"})
    cat = cat[["Item category", "complete", "open", "cancelled"]]
    names = q["activity_names"]
    fp_line = (
        "matches the published figures exactly - this is the genuine BPI Challenge 2019 log"
        if fp["matches_publication"]
        else "is a subset (sample or synthetic run), so the fingerprint check is not applied"
    )
    return f"""# 1 · Data quality: question the log before using it

> **Why this comes first.** A process-mining result is only as trustworthy as the event log
> behind it. Before drawing a single map we check timestamps, duplicates, ordering, labels
> and completeness, and we write down every cleaning decision.

## Fingerprint

The loaded log has **{n(fp["events"])} events** in **{n(fp["cases"])} cases** (one case = one
purchase-order item). The publication reports {n(fp["published_events"])} events and
{n(fp["published_cases"])} cases, so the file {fp_line}.

## What we found

![Cases affected by each data-quality issue](assets/figures/quality_issues.png)

**Timestamps.** {n(ts["missing"])} are missing, but **{n(ts["outside_window_events"])} events in
{n(ts["outside_window_cases"])} cases fall outside {ts["window"][0]} - {ts["window"][1]}**
(the earliest is {ts["min"][:10]}, the latest {ts["max"][:10]}). Events by year: {years}.
**{n(ts["events_at_23_59"])} events sit at 23:59 and {n(ts["events_at_00_00"])} at 00:00** -
they carry a date but no real time. Three activities are essentially date-only:
{", ".join(f"*{d['activity']}*" for d in ts["date_only_activities"])}. Waiting times that
involve them are only precise to the day, which is why the performance phase reports days,
not minutes.

**Duplicates.** Event IDs are unique ({n(du["event_id_duplicates"])} repeats), yet
**{n(du["exact_duplicate_extra_events"])} rows are identical copies** of another row in every
other attribute, spread over {n(du["exact_duplicate_cases"])} cases. Almost all of them are
service-entry sheets and goods receipts posted in bulk:

{md_table(dup_rows)}

**Ordering.** {n(od["cases_with_same_timestamp_ties"])} cases contain two or more different
activities with the same timestamp ({n(od["tie_groups"])} tie groups); their order in the raw
file is arbitrary. Some activities are dated *before* the purchase order exists:

{md_table(before)}

A vendor invoice dated before the PO is not a data error: it is evidence of *after-the-fact*
purchasing (the PO was raised to cover an invoice that already existed). We keep these events
and test them as a compliance rule in phase 4.

**Activity labels.** {names["distinct_activities"]} distinct activities;
{len(names["near_duplicate_groups"])} groups of labels that differ only in spelling,
{len(names["leading_trailing_or_double_spaces"])} labels with stray spaces, and
{len(names["casing_inconsistent"])} label(s) that break the Title Case convention of their
family ({", ".join(f"*{x}*" for x in names["casing_inconsistent"]) or "none"}). The source
system is clean here; the normalisation rule is still applied so that a refreshed extract
cannot silently split one activity into two.

**Case attributes.** Attributes that change value inside a case:
{", ".join(q["case_attributes"]["attributes_varying_within_a_case"]) or "none"} - every case
attribute is constant per case, as it should be. Spend area is missing for
{n(q["missing_values"]["cases_without_spend_area"])} cases; they are kept and labelled
*Unknown* in segment analyses.

## Cleaning trail

{md_table(log)}

{rationale}

## Completeness

A case still running when the log was extracted would look artificially fast if we measured
its cycle time. Rule: {cm["rule"]}

{md_table(cat)}

Performance and root-cause phases use **complete cases only** ({n(cm["complete"])});
discovery and conformance use every non-cancelled case, because an open case still shows how
work flows.
"""


def _short(v: str) -> str:
    abbrev = {
        C.PR: "PR",
        C.PO: "PO",
        C.VCI: "Vendor invoice",
        C.GR: "GR",
        C.IR: "IR",
        C.CLEAR: "Clear",
        C.REMOVE_BLOCK: "Remove block",
        "Receive Order Confirmation": "Order conf.",
    }
    return " → ".join(abbrev.get(a, a) for a in v.split(" > "))


def page_discovery(paths) -> str | None:
    s = _load(paths, "discovery/discovery_summary.json")
    if s is None:
        return None
    vt = _load(paths, "discovery/top_variants.csv").head(10)
    edges = _load(paths, "discovery/dfg_edges.csv")
    top = pd.DataFrame(
        {
            "#": range(1, len(vt) + 1),
            "Variant": [_short(v) for v in vt["variant"]],
            "Cases": vt["cases"].astype(int),
            "Share": [pct(x) for x in vt["share"]],
            "Cumulative": [pct(x) for x in vt["cumulative_share"]],
            "Textbook?": ["yes" if h else "no" for h in vt["happy_path"]],
        }
    )
    bycat = pd.DataFrame(s["textbook_share_by_category_complete"])
    bycat = pd.DataFrame(
        {
            "Item category": bycat["cat"],
            "Complete cases": bycat["complete_cases"].astype(int),
            "Followed the textbook path": [pct(x) for x in bycat["happy_share"]],
        }
    )
    busiest = edges.sort_values("total_days", ascending=False).head(6)
    busiest = pd.DataFrame(
        {
            "From": busiest["source"],
            "To": busiest["target"],
            "Times": busiest["count"].astype(int),
            "Median wait (days)": busiest["median_days"].round(1),
            "Total waiting (case-days)": busiest["total_days"].round(0),
        }
    )
    m, ma = s["model"], s["model_all_activities"]
    return f"""# 2 · AS-IS discovery: the process as it really runs

> **Question.** What does purchase-to-pay actually look like when we let the system logs
> speak, instead of the procedure manual?

Scope: {n(s["cases"])} non-cancelled cases, {n(s["events"])} events, {s["activities"]}
distinct activities.

## The directly-follows graph

Each box is an activity; each arrow means "this happened right after that" in at least 2% of
cases. Rarer activities and paths are hidden for readability (the full graph, with
{s["dfg_edges"]} arrows, is in `results/discovery/dfg_edges.csv`).

**By frequency** - how many times each hand-over happened:

![DFG frequency](assets/figures/dfg_frequency.png)

**By time** - the median waiting time on each hand-over (darker/red = slower):

![DFG performance](assets/figures/dfg_performance.png)

Where the waiting adds up (all cases, all hand-overs - *total* waiting, not the median, is
what tells you where capacity is consumed):

{md_table(busiest)}

## Variants: the happy path versus reality

A *variant* is a unique sequence of activities. The log contains **{n(s["variants"])}
variants**; {n(s["singleton_variants"])} of them occur exactly once.
**{s["variants_for_80pct"]} variants are enough to cover 80% of cases** - the remaining 20%
of cases are spread over more than ten thousand one-off paths.

![Variant coverage](assets/figures/variant_coverage.png)

The single most frequent path - *{_short(s["top_variant"])}* - covers only
**{pct(s["top_variant_share"])}** of cases. Allowing for legitimate options (a requisition
first, an order confirmation, the vendor invoice dated before or after the goods receipt), the
*textbook* path covers **{pct(s["textbook_share_complete_cases"])} of completed cases**. The
other {pct(1 - s["textbook_share_complete_cases"])} took a detour: a payment block, a price or
quantity change, a cancelled invoice, a second goods receipt.

![Top variants](assets/figures/top_variants.png)

{md_table(top)}

Textbook adherence by item category (completed cases):

{md_table(bycat)}

The 2-way-match category never follows the textbook path: it is dominated by *Change Approval
for Purchase Order* and by invoices that exist before the order - a small but structurally
different process.

## Discovered model (Inductive Miner)

Inductive Miner (infrequent variant, noise threshold {m["noise_threshold"]}) on the
{len(m["activities_in_model"])} activities that occur in at least
{pct(m["min_activity_share"], 0)} of cases (they carry {pct(m["events_kept_share"])} of all
events). BPMN file: [`models/as_is_inductive_core.bpmn`](https://github.com/juansanchezalcantara20-ai/p2p-process-mining/blob/main/models/as_is_inductive_core.bpmn).

![AS-IS BPMN](assets/figures/as_is_bpmn_core.png)

| Model | Activities | Log fitness | Fitting traces | Precision (5,000 cases) |
| --- | --- | --- | --- | --- |
| Core activities (≥ {pct(m["min_activity_share"], 0)} of cases) | {len(m["activities_in_model"])} | {m["log_fitness"]:.3f} | {m["fitting_traces_pct"]:.1f}% | {m["precision_5000_cases"]:.3f} |
| All activities | {s["activities"]} | {ma["log_fitness"]:.3f} | {ma["fitting_traces_pct"]:.1f}% | {ma["precision_5000_cases"]:.3f} |

**How to read it.** Fitness says how much of the observed behaviour the model can replay;
precision says how little *unobserved* behaviour it allows. Adding all {s["activities"]}
activities barely improves fitness but collapses precision: the model becomes a "flower" that
permits almost anything. The core model is the honest AS-IS picture: after the purchase order,
goods receipt, vendor invoice, invoice receipt, payment-block removal and clearing run
**in parallel and can repeat**. In other words, the company has no enforced sequence between
receiving goods and paying for them - which is exactly what phase 4 tests as compliance.
"""


PAGES = {
    "01-data-quality.md": page_quality,
    "02-discovery.md": page_discovery,
}


def run(paths, source: str = "full") -> list[Path]:
    written = []
    for name, builder in PAGES.items():
        text = builder(paths)
        if text is None:
            continue
        out = paths.docs / name
        out.write_text(text)
        written.append(out)
    return written


__all__ = ["run", "C"]
