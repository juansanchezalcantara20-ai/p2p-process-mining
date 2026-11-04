"""Phase 1b - question the event log before using it, then clean it with a documented trail.

Every check returns plain numbers so the report can be regenerated; every cleaning step
records how many events and cases it removed and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

from . import config as C

SMALL_WORDS = {"for", "of", "to", "in", "a", "an", "the", "and", "was"}


def _q(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def activity_name_issues(activities: pd.Series) -> dict:
    """Detect activity labels that differ only by case/whitespace/punctuation, and labels that
    break the naming convention of their family (e.g. 'Change payment term' among
    Title-Case 'Change X Y' labels)."""
    counts = activities.value_counts()
    names = list(counts.index)
    whitespace = [n for n in names if n != n.strip() or "  " in n]
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(_name_key(n), []).append(n)
    near_duplicates = [g for g in groups.values() if len(g) > 1]
    style = []
    for n in names:
        words = n.strip().split()
        if (
            len(words) > 1
            and not n.startswith("SRM:")
            and any(w[0].islower() for w in words[1:] if w[0].isalpha() and w not in SMALL_WORDS)
            and words[0] == "Change"
        ):
            style.append(n)
    return {
        "distinct_activities": len(names),
        "leading_trailing_or_double_spaces": whitespace,
        "near_duplicate_groups": near_duplicates,
        "casing_inconsistent": style,
    }


def canonical_activity_name(name: str) -> str:
    """Normalise whitespace and apply Title Case to inconsistent 'Change ...' labels."""
    clean = " ".join(name.split())
    words = clean.split(" ")
    if words and words[0] == "Change":
        clean = " ".join(
            w if w in SMALL_WORDS or not w[:1].isalpha() else w[:1].upper() + w[1:] for w in words
        )
    return clean


@dataclass
class QualityReport:
    fingerprint: dict = field(default_factory=dict)
    missing_values: dict = field(default_factory=dict)
    timestamps: dict = field(default_factory=dict)
    duplicates: dict = field(default_factory=dict)
    ordering: dict = field(default_factory=dict)
    activity_names: dict = field(default_factory=dict)
    case_attributes: dict = field(default_factory=dict)
    completeness: dict = field(default_factory=dict)
    cleaning_log: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def assess(df: pd.DataFrame, check_fingerprint: bool = True) -> QualityReport:
    """Run all data-quality checks on the canonical raw log (no mutation)."""
    rep = QualityReport()
    con = duckdb.connect()
    con.register("ev", df)

    n_events, n_cases = len(df), df["case_id"].nunique()
    rep.fingerprint = {
        "events": int(n_events),
        "cases": int(n_cases),
        "published_events": C.PUBLISHED_EVENTS,
        "published_cases": C.PUBLISHED_CASES,
        "matches_publication": bool(
            n_events == C.PUBLISHED_EVENTS and n_cases == C.PUBLISHED_CASES
        ),
        "checked": check_fingerprint,
    }

    miss = df.isna().sum()
    rep.missing_values = {
        "by_column": {k: int(v) for k, v in miss.items() if v > 0},
        "cases_without_spend_area": int(df.loc[df["spend_area"].isna(), "case_id"].nunique())
        if "spend_area" in df
        else 0,
        "events_with_user_NONE": int((df.get("user") == "NONE").sum()) if "user" in df else 0,
    }

    ts = _q(
        con,
        f"""
        select
          count(*) filter (where timestamp is null) as missing,
          count(*) filter (where timestamp < '{C.WINDOW_START}' or timestamp >= '{C.WINDOW_END}')
            as outside_window,
          count(distinct case_id) filter (
            where timestamp < '{C.WINDOW_START}' or timestamp >= '{C.WINDOW_END}')
            as cases_outside_window,
          min(timestamp) as min_ts, max(timestamp) as max_ts,
          count(*) filter (where strftime(timestamp, '%H:%M') = '23:59') as at_2359,
          count(*) filter (where strftime(timestamp, '%H:%M') = '00:00') as at_0000
        from ev
        """,
    ).iloc[0]
    by_year = _q(con, "select year(timestamp) y, count(*) n from ev group by 1 order by 1")
    date_only = _q(
        con,
        """
        select activity, count(*) n,
               avg(case when strftime(timestamp, '%H:%M') in ('23:59','00:00') then 1 else 0 end)
                 as share_date_only
        from ev group by 1 having share_date_only > 0.9 order by n desc
        """,
    )
    rep.timestamps = {
        "missing": int(ts["missing"]),
        "outside_window_events": int(ts["outside_window"]),
        "outside_window_cases": int(ts["cases_outside_window"]),
        "window": [C.WINDOW_START, C.WINDOW_END],
        "min": str(ts["min_ts"]),
        "max": str(ts["max_ts"]),
        "events_at_23_59": int(ts["at_2359"]),
        "events_at_00_00": int(ts["at_0000"]),
        "events_by_year": {
            str(int(r.y)) if pd.notna(r.y) else "null": int(r.n) for r in by_year.itertuples()
        },
        "date_only_activities": date_only.to_dict("records"),
    }

    key_cols = [c for c in df.columns if c != "event_id"]
    cols_sql = ", ".join(f'"{c}"' for c in key_cols)
    dup = _q(
        con,
        f"""
        select activity, sum(n - 1) as extra_copies, count(*) as groups
        from (select {cols_sql}, count(*) n from ev group by all having n > 1)
        group by activity order by extra_copies desc
        """,
    )
    rep.duplicates = {
        "event_id_duplicates": int(df["event_id"].duplicated().sum()) if "event_id" in df else 0,
        "exact_duplicate_extra_events": int(dup["extra_copies"].sum()) if len(dup) else 0,
        "exact_duplicate_cases": int(
            df[df.duplicated(subset=key_cols, keep=False)]["case_id"].nunique()
        ),
        "by_activity": dup.head(10).to_dict("records"),
    }

    order = _q(
        con,
        f"""
        with po as (
          select case_id, min(timestamp) po_ts from ev where activity = '{C.PO}' group by 1
        ), ties as (
          select case_id, timestamp, count(distinct activity) k from ev
          group by 1, 2 having k > 1
        )
        select
          (select count(distinct case_id) from ties) as cases_with_same_timestamp_ties,
          (select count(*) from ties) as tie_groups,
          (select count(distinct e.case_id) from ev e join po using (case_id)
             where e.timestamp < po.po_ts and e.activity not in
             ('{C.PR}', '{C.VCI}', 'Vendor creates debit memo')
             and e.activity not like 'SRM:%') as cases_with_events_before_po,
          (select count(distinct case_id) from ev e join po using (case_id)
             where e.activity = '{C.VCI}' and e.timestamp < po.po_ts)
             as cases_invoice_dated_before_po,
          (select count(*) from (select case_id from ev group by 1
             having count(*) filter (where activity = '{C.PO}') = 0)) as cases_without_po_event
        """,
    ).iloc[0]
    before_po = _q(
        con,
        f"""
        with po as (select case_id, min(timestamp) po_ts from ev where activity = '{C.PO}'
                    group by 1)
        select e.activity, count(distinct e.case_id) cases from ev e join po using (case_id)
        where e.timestamp < po.po_ts and e.activity <> '{C.PR}' and e.activity not like 'SRM:%'
        group by 1 order by 2 desc limit 8
        """,
    )
    rep.ordering = {k: int(v) for k, v in order.items()}
    rep.ordering["activities_dated_before_po"] = before_po.to_dict("records")

    rep.activity_names = activity_name_issues(df["activity"])

    present = [c for c in C.CASE_ATTRIBUTES if c in df.columns]
    nun = df.groupby("case_id")[present].nunique(dropna=False).max()
    rep.case_attributes = {
        "attributes_varying_within_a_case": [c for c, v in nun.items() if v > 1],
        "distinct_values": {c: int(df[c].nunique()) for c in present},
    }
    return rep


def case_status(df: pd.DataFrame) -> pd.Series:
    """Classify each case as complete / open / cancelled.

    * cancelled - the PO item was deleted and never reactivated;
    * complete  - invoice categories reached 'Clear Invoice'; consignment reached a goods
      receipt (consignment items are not invoiced at item level);
    * open      - everything else (still running when the log was extracted).
    """
    a = df["activity"]
    flags = pd.DataFrame(
        {
            "case_id": df["case_id"],
            "clear": (a == C.CLEAR),
            "gr": (a == C.GR),
            "del_ts": df["timestamp"].where(a == C.DELETE_ITEM),
            "react_ts": df["timestamp"].where(a == C.REACTIVATE_ITEM),
            "cat": df["item_category"],
        }
    )
    g = flags.groupby("case_id").agg(
        clear=("clear", "any"),
        gr=("gr", "any"),
        del_ts=("del_ts", "max"),
        react_ts=("react_ts", "max"),
        cat=("cat", "first"),
    )
    cancelled = g["del_ts"].notna() & ~(g["react_ts"].notna() & (g["react_ts"] > g["del_ts"]))
    complete = np.where(g["cat"] == C.CAT_CONSIGNMENT, g["gr"], g["clear"])
    return pd.Series(
        np.select([cancelled, complete], ["cancelled", "complete"], "open"),
        index=g.index,
        name="status",
    )


def clean(df: pd.DataFrame, rep: QualityReport) -> pd.DataFrame:
    """Apply the documented cleaning steps, logging each into ``rep.cleaning_log``."""

    def record(step: str, before: pd.DataFrame, after: pd.DataFrame, why: str) -> None:
        rep.cleaning_log.append(
            {
                "step": step,
                "events_removed": int(len(before) - len(after)),
                "cases_removed": int(before["case_id"].nunique() - after["case_id"].nunique()),
                "events_after": int(len(after)),
                "cases_after": int(after["case_id"].nunique()),
                "rationale": why,
            }
        )

    out = df.copy()
    out["activity"] = out["activity"].map(canonical_activity_name).astype("string")
    record(
        "Normalise activity labels",
        df,
        out,
        "Collapse whitespace and fix Title Case in 'Change ...' labels so one activity has "
        "one name.",
    )

    step = out[out["timestamp"].notna()]
    record("Drop events without timestamp", out, step, "An event without time cannot be ordered.")
    out = step

    bad = out.loc[
        (out["timestamp"] < C.WINDOW_START) | (out["timestamp"] >= C.WINDOW_END), "case_id"
    ].unique()
    step = out[~out["case_id"].isin(bad)]
    record(
        "Drop cases with timestamps outside the observation window",
        out,
        step,
        f"Events dated before {C.WINDOW_START} or after {C.WINDOW_END} (e.g. 1948, 2020) are "
        "data-entry errors; one impossible date makes the whole case's durations unreliable.",
    )
    out = step

    key_cols = [c for c in out.columns if c != "event_id"]
    step = out.drop_duplicates(subset=key_cols, keep="first")
    record(
        "Collapse exact duplicate events",
        out,
        step,
        "Rows identical in every attribute (same case, activity, minute, user and value) carry "
        "no extra timing or routing information but inflate loops and variant counts.",
    )
    out = step

    out = out.assign(_rank=out["activity"].map(C.ACTIVITY_RANK).fillna(C.DEFAULT_RANK))
    out = out.sort_values(["case_id", "timestamp", "_rank"], kind="mergesort").drop(columns="_rank")
    record(
        "Deterministic ordering",
        out,
        out,
        "Sort by case, timestamp, then canonical P2P position to break ties between "
        "date-only events (23:59/00:00) recorded on the same day.",
    )

    status = case_status(out)
    out = out.merge(status, left_on="case_id", right_index=True, how="left")
    vc = status.value_counts()
    rep.completeness = {
        "complete": int(vc.get("complete", 0)),
        "open": int(vc.get("open", 0)),
        "cancelled": int(vc.get("cancelled", 0)),
        "by_category": (
            out.drop_duplicates("case_id")
            .groupby(["item_category", "status"])
            .size()
            .unstack(fill_value=0)
            .to_dict("index")
        ),
        "rule": "complete = reached 'Clear Invoice' (consignment: a goods receipt); "
        "cancelled = PO item deleted and not reactivated; open = otherwise.",
    }
    return out.reset_index(drop=True)


def _write_json(obj: dict, path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


def plot_quality(rep: QualityReport, figures) -> None:
    from . import viz

    issues = {
        "Same-timestamp ties (order ambiguous)": rep.ordering["cases_with_same_timestamp_ties"],
        "Vendor invoice dated before PO": rep.ordering["cases_invoice_dated_before_po"],
        "Exact duplicate events": rep.duplicates["exact_duplicate_cases"],
        "Missing spend area": rep.missing_values["cases_without_spend_area"],
        "Other events before PO creation": rep.ordering["cases_with_events_before_po"],
        "Timestamp outside window": rep.timestamps["outside_window_cases"],
    }
    issues = dict(sorted(issues.items(), key=lambda kv: -kv[1]))
    fig, ax = viz.plt.subplots(figsize=(8, 3.6))
    viz.hbar(ax, issues.keys(), issues.values())
    ax.set_title("Cases affected by each data-quality issue")
    ax.set_xlabel("Cases")
    viz.save(fig, figures / "quality_issues.png")


def run(raw: pd.DataFrame, paths, check_fingerprint: bool = True) -> pd.DataFrame:
    """Phase 1 entry point: assess, clean, persist the report, return the clean log."""
    rep = assess(raw, check_fingerprint=check_fingerprint)
    if check_fingerprint and not rep.fingerprint["matches_publication"]:
        raise RuntimeError(
            f"Loaded log does not match the published fingerprint: {rep.fingerprint}"
        )
    cleaned = clean(raw, rep)
    _write_json(rep.to_dict(), paths.results / "quality" / "quality_report.json")
    pd.DataFrame(rep.cleaning_log).to_csv(
        paths.results / "quality" / "cleaning_log.csv", index=False
    )
    plot_quality(rep, paths.figures)
    return cleaned
