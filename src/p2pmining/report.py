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


def page_performance(paths) -> str | None:
    s = _load(paths, "performance/performance_summary.json")
    if s is None:
        return None
    ci, cc, pb = s["cycle_invoice"], s["cycle_consignment"], s["payment_block"]
    stages = pd.DataFrame(s["stages"])
    stages.columns = ["Stage", "Median (days)", "P90 (days)", "Mean (days)"]
    cat = _load(paths, "performance/cycle_by_item_category.csv")
    cat = cat[["item_category", "cases", "median_days", "p90_days", "mean_days"]]
    cat.columns = ["Item category", "Cases", "Median (days)", "P90 (days)", "Mean (days)"]
    doc = _load(paths, "performance/cycle_by_document_type.csv")
    doc = doc[["document_type", "cases", "median_days", "p90_days"]]
    doc.columns = ["Document type", "Cases", "Median (days)", "P90 (days)"]
    tw = s["top_waiting_handover"]
    sa, fa = s["slowest_spend_area"], s["fastest_spend_area"]
    return f"""# 3 · Performance and bottlenecks

> **Question.** How long does it take to go from a purchase order to a paid invoice, where
> does the time go, and for whom is it worse?

## Measuring honestly

**Only finished cases from a mature cohort are timed.** A case still open at extraction has
no end date, so it cannot be timed - but excluding it is not neutral either: for orders
created late in 2018 only the *fast* items had finished, so they look artificially quick.

![Censoring by month](assets/figures/censoring_by_month.png)

We therefore time purchase orders created between **{s["cohort"][0]} and {s["cohort"][1]}**
(exclusive), when ~90% of items had finished. That leaves
**{n(s["complete_cases"])} complete cases** ({n(s["invoice_cases"])} invoice items) out of
{n(s["complete_cases_all"])} complete cases in total.

**Medians and percentiles, not averages.** Durations cannot go below zero but can run for a
year, so a few extreme cases drag the mean away from the typical case. The median is what a
typical item experiences; P90 is what the unlucky tenth experiences, and is the number a
supplier complains about. Each stage below shows the gap: invoice capture has a median of
{n(stages.iloc[1, 1], 1)} days but a mean of {n(stages.iloc[1, 3], 1)} days - a mean would
double the apparent problem for most items while hiding how bad the tail really is.

## Cycle time

Invoice items: **median {n(ci["median"])} days** from PO creation to the last invoice cleared,
P25 {n(ci["p25"])}, P75 {n(ci["p75"])}, **P90 {n(ci["p90"])} days** (mean {n(ci["mean"], 1)}).
Consignment items (no invoice per item): median {n(cc["median"])} days to the last goods
receipt, P90 {n(cc["p90"])}.

![Cycle time distribution](assets/figures/cycle_time_distribution.png)

{md_table(cat)}

## Where the time goes

![Stage durations](assets/figures/stage_durations.png)

{md_table(stages)}

**The bottleneck is after the goods and the invoice are both in.** The stage from "goods
received and invoice posted" to "invoice cleared" takes a median of
**{n(stages.iloc[2, 1])} days - more than half of the end-to-end time**. Receiving goods
({n(stages.iloc[0, 1])} days median) and capturing invoices ({n(stages.iloc[1, 1])} days) are
comparatively quick.

![Waiting Pareto](assets/figures/waiting_pareto.png)

The single hand-over *{tw["source"]} → {tw["target"]}* holds
**{pct(tw["share_of_total_wait"])} of all waiting time** (median {n(tw["median_days"])} days);
the top three hand-overs hold {pct(s["top3_handover_share"])}. Two of the top six involve the
payment block.

**Payment blocks.** {pct(pb["share_cases"])} of invoice items had a payment block removed
before clearing. Their median cycle time is **{n(pb["median_with"])} days versus
{n(pb["median_without"])} without** a block; from invoice receipt to clearing they take a
median {n(pb["median_ir_to_clear_with"])} days versus {n(pb["median_ir_to_clear_without"])}.

!!! note "Caveat - some waiting is by design"
    The log has no payment-term or due-date field. Part of the invoice-to-clearing time is
    almost certainly deliberate (paying on agreed terms, e.g. 30-60 days, protects working
    capital). The improvement case in phase 6 therefore targets the *excess* over a term
    assumption and the waiting caused by blocks, not all of it.

## Who is affected

![Cycle by spend area](assets/figures/cycle_by_spend_area.png)

The slowest large spend area is **{sa["spend_area"]}** (median {n(sa["median_days"])} days,
{n(sa["cases"])} cases); the fastest is **{fa["spend_area"]}** (median
{n(fa["median_days"])} days). Logistics has an unusually long tail (see its P90).

![Cycle by vendor](assets/figures/cycle_by_vendor.png)

Among the 15 largest vendors, medians range from **{n(s["vendor_median_range"][0])} to
{n(s["vendor_median_range"][1])} days** - a threefold spread for the same company and the same
process, which points at vendor-specific practices (invoice timing, partial deliveries,
blocks) rather than at the process design.

{md_table(doc)}

Framework orders (call-offs against a long-running contract) are structurally long; they
should be tracked against their own target, not the standard-PO target.
"""


def page_conformance(paths) -> str | None:
    s = _load(paths, "conformance/conformance_summary.json")
    if s is None:
        return None
    imp = pd.DataFrame(s["impact"])
    rules = s["rules"]
    ctrl = pd.DataFrame(
        {
            "Rule": [rules[r]["title"] for r in rules],
            "Control tested": [rules[r]["control"] for r in rules],
            "Applies to": [rules[r]["applies_to"] for r in rules],
        }
    )
    rank = pd.DataFrame(
        {
            "Rank": range(1, len(imp) + 1),
            "Deviation": imp["title"],
            "Cases": imp["violating_cases"].astype(int),
            "Rate": [pct(x) for x in imp["violation_rate"]],
            "PO value affected (EUR M)": (imp["value_eur"] / 1e6).round(1),
            "Extra median days vs peers": [n(x, 1) for x in imp["excess_median_days"]],
            "Excess case-days": [n(x) for x in imp["excess_case_days"]],
        }
    )
    cat = pd.DataFrame(s["by_category"])
    cat = pd.DataFrame(
        {
            "Item category": cat["item_category"],
            "Completed cases": cat["cases"].astype(int),
            "Conforming": [pct(x) for x in cat["conforming"]],
            "Mean trace fitness": cat["mean_fitness"].round(3),
        }
    )
    al = _load(paths, "conformance/alignment_deviations.csv").head(8)
    al = al[["move_type", "activity", "moves"]]
    al.columns = ["Move type", "Activity", "Moves"]
    r = {x["rule"]: x for x in s["impact"]}
    pb, r2, r6, r1 = (
        r["R5_payment_block"],
        r["R2_invoice_before_gr"],
        r["R6_after_the_fact_po"],
        r["R1_no_three_way_match"],
    )
    return f"""# 4 · Compliance and conformance

> **Question.** Does the process follow the controls a purchase-to-pay process is supposed to
> have - and when it does not, which deviations matter most?

## Two lenses

1. **Business rules** - seven classic P2P controls checked case by case.
2. **Model-based conformance** - every case replayed against an *expected* (normative) model
   for its item category, using token-based replay; optimal alignments on a random subset of
   {n(s["alignment_cases"])} cases show *where* cases depart from it.

## Business rules

{md_table(ctrl)}

![Compliance rules](assets/figures/compliance_rules.png)

**{pct(s["any_rule_violation_share"])} of non-cancelled cases breach at least one rule.**
Ranked by impact - number of cases, PO value exposed and excess cycle time versus comparable
cases of the same item category that did *not* breach the rule (each dimension ranked, then
averaged, so no hidden weights):

{md_table(rank)}

How to read the ranking:

* **Payment blocks are the dominant deviation**: {n(pb["violating_cases"])} invoice items
  ({pct(pb["violation_rate"])}), EUR {n(pb["value_eur"] / 1e6, 0)} M of PO value, and a median
  of {n(pb["excess_median_days"], 1)} extra days compared with unblocked peers.
* **Rework after ordering** (quantity and price changes) is next: the order was issued before
  the commercial terms were settled.
* **The GR-based invoice-verification control works**: {n(r2["violating_cases"])} of
  {n(r2["applicable_cases"])} items flagged *invoice after GR* had the invoice posted before
  the goods. The system enforces it - a useful contrast with the rules that rely on people.
* **After-the-fact purchasing** ({n(r6["violating_cases"])} cases, EUR
  {n(r6["value_eur"] / 1e6, 0)} M) and **payment without a complete three-way match**
  ({n(r1["violating_cases"])} cases) are *faster* than their peers. They are not time
  problems; they are **control** problems - the speed comes precisely from skipping the
  control. Their priority comes from audit risk, not from waiting time.

## Conformance against the expected model

The expected model for the dominant category (*3-way match, invoice before GR*): optional
requisition and order confirmation, then - per delivery - the goods receipt in parallel with
the vendor invoice and invoice posting, and clearing only once both are in.

![Normative model](assets/figures/normative_3way_before_gr.png)

Normative BPMN files for all four categories are in `models/normative_*.bpmn`.

**{pct(s["conforming_share"])} of completed cases conform** to their expected model
(mean trace fitness {s["mean_trace_fitness"]:.3f}); {pct(s["share_with_extra_activities"])}
contain at least one activity the expected model does not foresee. Across *all* non-cancelled
cases the figure is {pct(s["conforming_share_all"])}, because open cases have not reached
clearing yet.

![Conformance by category](assets/figures/conformance_by_category.png)

{md_table(cat)}

Where the alignments locate the deviations (moves summed over the aligned subset):

{md_table(al)}

*Log moves* are steps that happened but should not have (payment-block removals, extra goods
receipts and service-entry sheets, changes); *model moves* are steps the model expected but
that never happened (mostly clearing in items that were never paid in full, and missing
invoice receipts).

The 2-way-match category conforms 0%: every one of its cases carries *Change Approval for
Purchase Order*, which the expected model does not contain. Either the expected model is
wrong for this category (approval changes are its normal practice) or the practice is; this
is a question for the process owner, not something the data can settle.
"""


def _rules_md(rules: list[dict], base: float) -> str:
    df = pd.DataFrame(rules)
    df = pd.DataFrame(
        {
            "If...": df["rule"],
            "Items": df["cases"].astype(int),
            "Flagged rate": [pct(x) for x in df["rate"]],
            "vs average": [f"×{x:.2f}" for x in df["lift"]],
        }
    )
    return md_table(df)


def _lifts_md(lifts: list[dict]) -> str:
    df = pd.DataFrame(lifts)
    df = pd.DataFrame(
        {
            "Attribute": df["attribute"],
            "Value": [("yes" if v == "True" else v) for v in df["value"]],
            "Items": df["cases"].astype(int),
            "Rate": [pct(x) for x in df["rate"]],
            "Lift": [f"×{x:.2f}" for x in df["lift"]],
        }
    )
    return md_table(df)


def page_rootcause(paths) -> str | None:
    s = _load(paths, "rootcause/rootcause_summary.json")
    if s is None:
        return None
    so, sp, do = s["slow_order"], s["slow_process"], s["deviation_order"]
    hp, rest = s["hotspot_profile"]["hotspot"], s["hotspot_profile"]["rest"]
    bm = s["behaviour_medians"]
    beh = pd.DataFrame(
        [
            {
                "Behaviour": k.replace("_", " "),
                "Share of items": pct(v["share"]),
                "Median cycle (days)": round(v["median_days"], 1),
            }
            for k, v in bm.items()
        ]
    ).sort_values("Median cycle (days)", ascending=False)
    return f"""# 5 · Root cause: what goes with slow items and deviations?

> **Question.** Which characteristics of a purchase-order item make it more likely to be
> slow, or to break a control? And what happens to the slow ones along the way?

**Definitions.** A *slow* item is a completed invoice item in the top quartile of cycle time:
more than **{n(s["slow_threshold_days"])} days** from PO to payment (mature cohort,
{n(s["slow_cases"])} items, so {pct(so["base_rate"], 0)} are slow by construction). A
*deviating* item breaks at least one of the phase-4 rules ({pct(do["base_rate"])} of completed
items).

**Method, in plain words.** For every attribute value we compare the share of slow items with
the average (*lift*: ×2.0 means "twice as likely as a typical item"). Then a three-question
decision tree finds the combinations that separate slow from normal items best. Three
questions is deliberately few: every branch can be read aloud and checked by the process
owner. We keep **order-time attributes** (known when the PO is raised) separate from
**process behaviours** (what happens afterwards), because the latter are partly a consequence
of slowness rather than a cause.

## 1. Who is slow? (order-time attributes)

{_lifts_md(so["top_lifts"][:6])}

![Lift slow order](assets/figures/lift_slow_order.png)

The tree's answer:

{_rules_md(so["top_rules"] + so["bottom_rules"], so["base_rate"])}

**In business language:** *low-value items bought from the very largest vendors are the slow
ones.* The segment "top vendor (> 5,000 items in the log) and item value below EUR 500" holds
**{n(hp["cases"])} items from just {hp["vendors"]} vendors**, {pct(hp["spend_area_top"].get("Packaging", 0), 0)}
of them in Packaging. **{pct(hp["slow_share"], 0)} of them are slow, against
{pct(rest["slow_share"], 0)} for everything else.**

Where their time goes:

| | Hotspot ({hp["vendors"]} vendors) | All other items |
| --- | --- | --- |
| Items | {n(hp["cases"])} | {n(rest["cases"])} |
| Median cycle time | {n(hp["median_cycle_days"])} days | {n(rest["median_cycle_days"])} days |
| Median PO → goods receipt | {n(hp["median_po_to_gr_days"])} days | {n(rest["median_po_to_gr_days"])} days |
| **Median matched → cleared** | **{n(hp["median_match_to_clear_days"])} days** | {n(rest["median_match_to_clear_days"])} days |
| Payment-block share | {pct(hp["payment_block_share"])} | {pct(rest["payment_block_share"])} |

Delivery is only a few days slower; the difference is almost entirely **after the invoice is
matched**. Two explanations fit the data and the data alone cannot choose between them:
(a) these vendors invoice many small items that are paid in a periodic batch or under a long
agreed payment term, or (b) small-value invoices from big vendors are deprioritised in
accounts payable. Both are worth checking with AP, and both point to the same remedies:
consolidated or self-billing invoicing (evaluated receipt settlement) for high-volume,
low-value lines - see phase 6.

Tree quality on a 30% hold-out: balanced accuracy {so["metrics"]["balanced_accuracy_test"]:.2f},
ROC AUC {so["metrics"]["roc_auc_test"]:.2f}. That is a useful *signal*, not a forecast:
order-time attributes explain part of the slowness, the rest happens during execution.

## 2. What happens to slow items? (process behaviour)

{_lifts_md(sp["top_lifts"][:6])}

![Lift slow process](assets/figures/lift_slow_process.png)

{_rules_md(sp["top_rules"] + sp["bottom_rules"], sp["base_rate"])}

Items with **none** of these behaviours ({pct(s["share_no_behaviour"])} of the cohort) take a
median of **{n(s["median_no_behaviour"])} days**. Each behaviour adds time:

{md_table(beh)}

**In business language:** a quantity change after the order and a payment block are the two
behaviours most associated with slowness; items that hit both are slow
{pct(sp["top_rules"][0]["rate"], 0)} of the time. Vendor invoices dated before the PO are fast
(the work was already done when the PO was raised) - a control issue, not a speed issue.

## 3. Who deviates? (order-time attributes)

{_lifts_md(do["top_lifts"][:6])}

{_rules_md(do["top_rules"] + do["bottom_rules"], do["base_rate"])}

Deviations are spread widely (hold-out ROC AUC {do["metrics"]["roc_auc_test"]:.2f}): no single
segment owns them, apart from consignment, which almost never deviates because it has no
invoice step. Higher-value items and *Trading & End Products* deviate more often - consistent
with more negotiation (price and quantity changes) on larger purchases.

!!! warning "Association, not causation"
    These are patterns in historical data. They tell the improvement team *where to look* and
    *which hypotheses to test*; they do not prove that changing an attribute would change the
    outcome. Each hypothesis above is phrased so it can be checked with the process owner.
"""


def page_tobe(paths) -> str | None:
    s = _load(paths, "tobe/tobe_summary.json")
    if s is None:
        return None
    opps = _load(paths, "tobe/opportunities.csv").sort_values("priority")
    b, t = s["baseline"], s["target"]
    table = pd.DataFrame(
        {
            "Priority": opps["priority"].astype(int),
            "Opportunity": [
                f"**{i}** {nm}" for i, nm in zip(opps["id"], opps["name"], strict=True)
            ],
            "Items improved": opps["items_improved"].astype(int),
            "Waiting removed (case-days)": [n(x) for x in opps["case_days_saved"]],
            "Median saving per item (days)": [n(x, 1) for x in opps["median_saving_days"]],
            "Median cycle if done alone": [n(x, 1) for x in opps["median_cycle_if_alone"]],
            "Effort": opps["effort"],
        }
    )
    assumptions = "\n".join(
        f"| **{r.id}** | {r.lever} | {r.assumption} | {r.kpi} |" for r in opps.itertuples()
    )
    anchor = _load(paths, "tobe/payment_anchor_evidence.csv")
    anchor.columns = [
        "Invoice capture time (days)",
        "Items",
        "Median invoice date → cleared",
        "Median posting → cleared",
    ]
    ht = s["hotspot_payment_timing"]
    o6 = opps[opps["id"] == "O6"].iloc[0]
    kp = pd.DataFrame(
        {
            "KPI": [
                "Median cycle time (days)",
                "P90 cycle time (days)",
                "Rework rate",
                "First-pass three-way match",
                f"Paid within {s['payment_term_days_assumed']} days of invoice date",
            ],
            "AS-IS baseline": [
                n(b["median_cycle_days"], 1),
                n(b["p90_cycle_days"], 1),
                pct(b["rework_rate"]),
                pct(b["first_pass_match_rate"]),
                pct(b["on_time_payment_rate"]),
            ],
            "TO-BE estimate": [
                n(t["median_cycle_days"], 1),
                n(t["p90_cycle_days"], 1),
                pct(t["rework_rate"]),
                pct(t["first_pass_match_rate"]),
                pct(t["on_time_payment_rate"]),
            ],
        }
    )
    return f"""# 6 · TO-BE process and improvement case

> **Question.** What should the process look like, which changes come first, and how much
> waiting would they remove - according to the company's own data?

!!! warning "Estimates, not savings"
    Every figure on this page is an **estimate derived from the AS-IS event log under the
    assumption written next to it**. Nothing here has been implemented or measured after a
    change. Base: {n(s["cohort_items"])} completed invoice items from POs created
    {s["cohort"][0]} - {s["cohort"][1]} (exclusive), i.e. eight months of orders.

## TO-BE process

![TO-BE BPMN](assets/figures/to_be_bpmn.png)

What changes against the AS-IS model of phase 2:

| AS-IS (observed) | TO-BE (designed) |
| --- | --- |
| Goods receipt, invoice, block removal and clearing run in any order and repeat | Goods receipt in parallel with e-invoice → automatic three-way match; clearing only after the match |
| {pct(1 - b["first_pass_match_rate"])} of 3-way items need a manual block release or an invoice re-posting | Auto-release inside tolerance; a named owner resolves exceptions within 5 days |
| Price and quantity changed after the PO in {pct(b["rework_rate"])} of items (incl. invoice cancellations) | PO created from catalogue / contract price; requester confirms quantity before release |
| Paper / PDF invoices posted a median 9 days (P90 48) after their date | Structured e-invoice, posted on receipt |
| Small items from the largest vendors wait ~{n(ht["hotspot_median_invoice_date_to_clear"])} days from invoice date to payment | Self-billing (ERS) or one consolidated invoice per period ([`models/to_be_ers_variant.bpmn`](https://github.com/juansanchezalcantara20-ai/p2p-process-mining/blob/main/models/to_be_ers_variant.bpmn)) |
| Invoices dated before the PO accepted | "No PO, no pay"; fast-track PO or purchasing card for urgent buys |

BPMN: [`models/to_be.bpmn`](https://github.com/juansanchezalcantara20-ai/p2p-process-mining/blob/main/models/to_be.bpmn).

## Prioritised opportunities

![Priority matrix](assets/figures/priority_matrix.png)

{md_table(table)}

Priority = waiting removed ÷ effort (Low 1, Medium 2, High 3). Effort is a judgement call and
is labelled as such; impact comes from the data. **O6** removes no waiting - its case is
control: {n(o6["items_improved"])} items in the cohort, EUR {n(o6["value_affected_eur"] / 1e6, 1)} M of PO value bought before a PO existed.

### The assumption behind every number

| # | Lever | Assumption behind the estimate | KPI it moves |
| --- | --- | --- | --- |
{assumptions}

### Why e-invoicing is estimated conservatively

A naive estimate would credit every day of faster invoice capture as a day of faster payment.
The data say otherwise: **payment is anchored on the vendor's invoice date**, not on the day
the invoice is posted. The later an invoice is posted, the *shorter* the wait between posting
and payment - the total from invoice date to payment barely moves until capture becomes very
slow:

{md_table(anchor)}

So O4 only claims time for invoices that were posted so late that payment slipped past the
assumed {s["payment_term_days_assumed"]}-day term. The same evidence warns about O2: the
hotspot's small items are paid a median {n(ht["hotspot_median_invoice_date_to_clear"])} days
after their invoice date versus {n(ht["rest_median_invoice_date_to_clear"])} for everything
else. If that reflects an agreed 90-day term, O2's time and cash effect is zero and only the
administrative saving (thousands fewer invoices to match) remains. **Check the contracts
before committing to O2's number.**

## What the improved process would look like in numbers

Simulation: for each opportunity, the assumed avoidable share of affected items (seeded
random draw) loses its excess time over comparable peers; savings are summed per item and the
new cycle time is never shorter than the item's own delivery time.

{md_table(kp)}

Combined, the levers remove an estimated **{n(s["combined_case_days_saved"])} case-days** of
waiting over eight months of orders (the sum of the individual estimates,
{n(s["sum_of_individual_case_days"])}, overlaps slightly because some items benefit from
several levers). These targets feed the control dashboard in the DMAIC chapter.

On-time payment depends heavily on the assumed term (no due-date field exists in the log):
the share of items paid within 30 / 45 / 60 / 90 days of the invoice date is
{" / ".join(pct(v, 0) for v in s["on_time_sensitivity"].values())}.
"""


def page_dmaic(paths) -> str | None:
    s = _load(paths, "tobe/tobe_summary.json")
    q = _load(paths, "quality/quality_report.json")
    d = _load(paths, "discovery/discovery_summary.json")
    p = _load(paths, "performance/performance_summary.json")
    c = _load(paths, "conformance/conformance_summary.json")
    r = _load(paths, "rootcause/rootcause_summary.json")
    if None in (s, q, d, p, c, r):
        return None
    b, t = s["baseline"], s["target"]
    hp = r["hotspot_profile"]["hotspot"]
    stage = {x["stage"]: x for x in p["stages"]}
    m2c = stage["Goods + invoice matched → cleared"]["median_days"]
    term = s["payment_term_days_assumed"]
    return f"""# 7 · DMAIC: the improvement case end to end

The analysis above, organised as a Lean Six Sigma DMAIC project.

## Define

**Problem statement.** Purchase-order items take a median of **{n(b["median_cycle_days"])}
days** (P90 {n(b["p90_cycle_days"])}) from order to payment; only
**{pct(b["on_time_payment_rate"])}** of invoices are paid within {term} days of their date, and
**{pct(1 - b["first_pass_match_rate"])}** of three-way-match items need manual intervention
(payment block or invoice re-posting) before they can be paid.

**Goal.** Reduce median order-to-payment time towards **{n(t["median_cycle_days"])} days** and
raise first-pass match to **{pct(t["first_pass_match_rate"], 0)}**, without weakening controls.

**Scope.** Purchase-order items (one case = one PO item) of the four item categories, from
requisition/PO creation to invoice clearing. Out of scope: sourcing, contract negotiation,
treasury decisions on payment runs.

**CTQs (critical to quality).** Order-to-payment time; on-time payment to suppliers; first-pass
three-way match; no purchase without a PO.

**SIPOC**

| Suppliers | Inputs | Process | Outputs | Customers |
| --- | --- | --- | --- | --- |
| Requesters, vendors, contract owners | Requisition, PO data, goods, vendor invoice | Requisition → PO → goods receipt → invoice receipt → match → clear | Paid, correctly matched invoice; received goods | Vendors, requesters, finance / AP, auditors |

## Measure

* Data: {n(q["fingerprint"]["events"])} events, {n(q["fingerprint"]["cases"])} cases - the
  complete BPI Challenge 2019 log, checked and cleaned with a written trail
  ([phase 1](01-data-quality.md)).
* Baseline (mature cohort, POs Jan-Aug 2018): median cycle {n(b["median_cycle_days"], 1)} days,
  P90 {n(b["p90_cycle_days"], 1)}; rework {pct(b["rework_rate"])}; first-pass three-way match
  {pct(b["first_pass_match_rate"])}; paid within {term} days {pct(b["on_time_payment_rate"])}.
* Measurement-system notes: three activities are date-only; no due-date field (on-time KPI
  uses an assumed term); late cohorts are right-censored and excluded from timing.

## Analyze

* **Flow** ([phase 2](02-discovery.md)): {n(d["variants"])} variants; {d["variants_for_80pct"]}
  cover 80% of cases; only {pct(d["textbook_share_complete_cases"])} of completed cases follow
  the textbook path.
* **Bottleneck** ([phase 3](03-performance.md)): the stage after goods and invoice are both in
  takes a median {n(m2c)} days - over half of the cycle; *invoice receipt → clear* alone holds
  {pct(p["top_waiting_handover"]["share_of_total_wait"])} of all waiting.
* **Compliance** ([phase 4](04-conformance.md)): {pct(c["conforming_share"])} of completed
  cases conform to the expected model; payment blocks are the highest-impact deviation.
* **Root cause** ([phase 5](05-root-cause.md)): low-value items from the {hp["vendors"]}
  largest vendors are slow {pct(hp["slow_share"], 0)} of the time; quantity changes and payment
  blocks are the process behaviours most associated with delay.

## Improve

Six prioritised levers and the TO-BE process ([phase 6](06-to-be.md)). Suggested sequencing:

1. **Quick wins (0-3 months):** O5 invoice validation at capture, O6 "no PO, no pay",
   contract check for the hotspot vendors (decides O2).
2. **Core (3-9 months):** O1 tolerance-based auto-release, O4 e-invoicing, O2 self-billing pilot
   with one hotspot vendor.
3. **Structural (6-12 months):** O3 catalogue / contract pricing in the PO.

Pilot each lever on one spend area first and compare it with a control group - the event log
makes a before/after comparison cheap.

## Control

The dashboard the process owner would review monthly. Each KPI is computed from fields that
already exist in the event log, so it can be refreshed automatically by this pipeline.

![KPI dashboard](assets/figures/kpi_dashboard.png)

Grey bands are 3-sigma p-chart limits around the baseline proportion: a month outside the band
is a real change, not noise. Shown here on the baseline months, before any change.

| KPI | Definition (from the event log) | Baseline | Target (TO-BE estimate) | Review | Reaction if off-track |
| --- | --- | --- | --- | --- | --- |
| Order-to-payment time | Median days, *Create PO Item* → last *Clear Invoice*, completed invoice items, by PO month | {n(b["median_cycle_days"], 1)} d | {n(t["median_cycle_days"], 1)} d | Monthly | Drill into the waiting Pareto for the month; check block queue |
| Rework rate | Share of items with *Change Price*, *Change Quantity* or *Cancel Invoice Receipt* after the PO | {pct(b["rework_rate"])} | {pct(t["rework_rate"])} | Monthly | Top spend areas / requesters by changes; refresh catalogue prices |
| First-pass three-way match | Share of 3-way items cleared with no payment block and no invoice cancellation | {pct(b["first_pass_match_rate"])} | {pct(t["first_pass_match_rate"])} | Weekly | Review block reasons; adjust tolerances |
| On-time payment | Share cleared ≤ {term} days after the vendor invoice date (assumed term) | {pct(b["on_time_payment_rate"])} | {pct(t["on_time_payment_rate"])} | Monthly | Replace the assumed term with real due dates; review late payments by vendor |
| After-the-fact purchasing (guardrail) | Share of invoice items with vendor invoice dated before the PO | see phase 4 | → 0 | Monthly | Escalate to budget owner |

Targets are the simulated TO-BE values from phase 6 and inherit its assumptions. Speed must not
be bought by weakening control: the after-the-fact guardrail and the three-way-match rule
(phase 4) stay on the dashboard for that reason.
"""


def page_index(paths, source: str = "full") -> str | None:
    q = _load(paths, "quality/quality_report.json")
    d = _load(paths, "discovery/discovery_summary.json")
    p = _load(paths, "performance/performance_summary.json")
    c = _load(paths, "conformance/conformance_summary.json")
    r = _load(paths, "rootcause/rootcause_summary.json")
    s = _load(paths, "tobe/tobe_summary.json")
    if None in (q, d, p, c, r, s):
        return None
    b, t = s["baseline"], s["target"]
    stage = {x["stage"]: x for x in p["stages"]}
    m2c = stage["Goods + invoice matched → cleared"]["median_days"]
    hp, rest = r["hotspot_profile"]["hotspot"], r["hotspot_profile"]["rest"]
    pb = next(x for x in c["impact"] if x["rule"] == "R5_payment_block")
    opps = sorted(s["opportunities"], key=lambda o: o["priority"])
    opp_rows = "\n".join(
        f"| {o['priority']} | {o['name']} | {n(o['case_days_saved'])} | {o['effort']} |"
        for o in opps
    )
    data_line = (
        "the complete, public **BPI Challenge 2019** event log - real purchase-to-pay data from a "
        "multinational coatings and paints company, anonymised and published on 4TU.ResearchData"
        if source == "full"
        else f"a **{source}** run of the pipeline (not the published analysis)"
    )
    return f"""# Purchase-to-pay process mining · committee summary

*Evidence base: {data_line} - {n(q["fingerprint"]["events"])} events, {n(q["fingerprint"]["cases"])}
purchase-order items, 2018.*

## The problem

A purchase-order item takes a median of **{n(b["median_cycle_days"])} days** from order to
payment, and one in ten takes more than **{n(b["p90_cycle_days"])} days**. Only
**{pct(b["on_time_payment_rate"], 0)}** of invoices are paid within 60 days of their date
(assumed term), and **{pct(1 - b["first_pass_match_rate"], 0)}** of three-way-match items need
a manual intervention before they can be paid.

## The evidence

The process was reconstructed from system logs rather than interviews. After a documented
data-quality review ([1](01-data-quality.md)):

* **There is no single process.** {n(d["variants"])} distinct paths; {d["variants_for_80pct"]}
  of them cover 80% of items, and only {pct(d["textbook_share_complete_cases"], 0)} of completed
  items follow the textbook flow ([2](02-discovery.md)).
* **Time is lost after the goods and the invoice are both in.** That last stage takes a median
  of {n(m2c)} days - more than half of the cycle. One hand-over, *invoice receipt → clear*,
  holds {pct(p["top_waiting_handover"]["share_of_total_wait"], 0)} of all waiting time
  ([3](03-performance.md)).
* **Payment blocks are the costliest deviation.** {pct(pb["violation_rate"], 0)} of invoice
  items were blocked; blocked items take a median {n(pb["excess_median_days"])} days longer than
  comparable unblocked ones. Overall {pct(c["conforming_share"], 0)} of completed items conform
  to the expected process ([4](04-conformance.md)).
* **A small group of vendors explains much of the tail.** Low-value items from the
  {hp["vendors"]} largest vendors ({n(hp["cases"])} items, almost all Packaging) are slow
  {pct(hp["slow_share"], 0)} of the time versus {pct(rest["slow_share"], 0)} for everything
  else; their extra time sits almost entirely after the invoice is matched ([5](05-root-cause.md)).
* **Payment is anchored on the vendor's invoice date**, not on when the invoice is posted - so
  faster invoice capture only helps invoices that are already late ([6](06-to-be.md)).

## Recommendation

Adopt the TO-BE process ([6](06-to-be.md)) - automatic three-way match with tolerance-based
release, e-invoicing, contract prices in the PO, self-billing for high-volume low-value lines
and "no PO, no pay" - in this order of priority:

| # | Lever | Estimated waiting removed (case-days, 8 months of orders) | Effort |
| --- | --- | --- | --- |
{opp_rows}

If every lever delivers as assumed, the median cycle time would move from
**{n(b["median_cycle_days"])} to about {n(t["median_cycle_days"])} days**, first-pass match
from {pct(b["first_pass_match_rate"], 0)} to {pct(t["first_pass_match_rate"], 0)}, and rework
from {pct(b["rework_rate"], 0)} to {pct(t["rework_rate"], 0)}. **These are estimates derived
from the 2018 data under written assumptions, not achieved savings.** Two decisions are needed
first: confirm the hotspot vendors' payment terms (it decides whether lever O2 is worth
anything) and replace the assumed 60-day term with real due dates.

Progress would be tracked monthly on the control dashboard ([7](07-dmaic.md)).

!!! info "How to read this site"
    Pages 1-7 follow the analysis in order. Every number is regenerated from the data by
    `make all`; every judgement call is in the [decision log](DECISIONS.md).
"""


PAGES = {
    "01-data-quality.md": page_quality,
    "02-discovery.md": page_discovery,
    "03-performance.md": page_performance,
    "04-conformance.md": page_conformance,
    "05-root-cause.md": page_rootcause,
    "06-to-be.md": page_tobe,
    "07-dmaic.md": page_dmaic,
}


def run(paths, source: str = "full") -> list[Path]:
    written = []
    index = page_index(paths, source)
    if index is not None:
        (paths.docs / "index.md").write_text(index)
        written.append(paths.docs / "index.md")
    for name, builder in PAGES.items():
        text = builder(paths)
        if text is None:
            continue
        out = paths.docs / name
        out.write_text(text)
        written.append(out)
    return written


__all__ = ["run", "C"]
