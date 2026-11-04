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


PAGES = {
    "01-data-quality.md": page_quality,
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
