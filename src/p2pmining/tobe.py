"""Phase 6 - TO-BE process, quantified improvement case and DMAIC control dashboard.

Every impact figure here is an **estimate derived from the AS-IS data under an explicit,
written assumption** - never a realised saving. Assumptions live next to the numbers in
``ASSUMPTIONS`` and are rendered verbatim into the report.

The what-if simulation works per case on the mature cohort of completed invoice items:

1. for each opportunity, a seeded random share ``p`` of the affected cases (the assumed
   avoidable share) receives a saving;
2. the saving is the excess that the case shows over comparable peers, capped so it never
   exceeds the case's own observed wait in the stage the opportunity acts on;
3. savings from several opportunities are summed per case, and the new cycle time is floored
   at the case's own PO-to-goods-receipt time (delivery is not touched by any opportunity).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as C
from . import viz

SEED = 42
PAYMENT_TERM_DAYS = 60  # assumed contractual term for the on-time payment KPI
TARGET_CAPTURE_DAYS = 3  # e-invoicing target from vendor invoice date to posting

ASSUMPTIONS = {
    "O1": {
        "name": "Auto-release matched invoices (remove avoidable payment blocks)",
        "lever": "Tolerance-based automatic three-way match; blocks only for true exceptions; "
        "daily exception queue with an owner and a 5-day SLA.",
        "p_avoidable": 0.5,
        "assumption": "Half of today's payment blocks are avoidable (e.g. small price/quantity "
        "differences inside a tolerance). For each avoided block the item loses its excess "
        "matched-to-cleared time over unblocked items of the same category, capped at the "
        "category's median excess.",
        "effort": "Medium",
        "kpi": "First-pass match rate, cycle time",
    },
    "O2": {
        "name": "Self-billing / consolidated invoicing for high-volume, low-value lines",
        "lever": "Evaluated receipt settlement (pay on goods receipt, no vendor invoice) or "
        "one consolidated invoice per period for the largest vendors' small items.",
        "p_avoidable": 1.0,
        "assumption": "For items from vendors with > 5,000 items in the log and value below "
        "EUR 500 (the root-cause hotspot), matched-to-cleared time falls to the median of all "
        "other items. If the long wait is a contractual payment term, the time and cash impact "
        "is zero and only the administrative saving remains - verify terms first.",
        "effort": "Medium",
        "kpi": "Cycle time, on-time payment",
    },
    "O3": {
        "name": "Settle price and quantity before the PO is issued",
        "lever": "Catalogue/contract prices in the PO, quantity confirmation from the "
        "requester, PO approval checks the price against the contract.",
        "p_avoidable": 0.5,
        "assumption": "Half of post-PO price/quantity changes are preventable. Each prevented "
        "change removes the item's excess cycle time over unchanged items of the same "
        "category, capped at the category's median excess.",
        "effort": "High",
        "kpi": "Rework rate, cycle time",
    },
    "O4": {
        "name": "E-invoicing to cut invoice capture time",
        "lever": "Structured e-invoices / OCR with automatic posting.",
        "p_avoidable": 1.0,
        "assumption": f"Capture time (vendor invoice date → invoice posted) falls to at most "
        f"{TARGET_CAPTURE_DAYS} days. The data show that payment is anchored on the vendor's "
        "invoice date, not on the posting date, so faster capture only helps items that were "
        f"paid later than the assumed {PAYMENT_TERM_DAYS}-day term: the saving is the smaller "
        "of (capture time beyond target) and (days paid beyond the term).",
        "effort": "Medium",
        "kpi": "Cycle time",
    },
    "O5": {
        "name": "Validate invoices at capture (fewer cancellations and re-postings)",
        "lever": "Mandatory PO reference and line validation before posting.",
        "p_avoidable": 0.5,
        "assumption": "Half of invoice cancellations are preventable; each removes the item's "
        "excess cycle time over items without cancellation, capped at the category median "
        "excess.",
        "effort": "Low",
        "kpi": "Rework rate, first-pass match rate",
    },
    "O6": {
        "name": "Enforce 'no PO, no pay' (after-the-fact purchasing)",
        "lever": "Reject invoices without a prior PO; route urgent buys through a "
        "fast-track PO or procurement card.",
        "p_avoidable": None,
        "assumption": "Control and audit-risk improvement. These items are faster than peers, "
        "so no cycle-time saving is claimed; the impact is the PO value bought outside the "
        "control.",
        "effort": "Low",
        "kpi": "Compliance (after-the-fact rate)",
    },
}


# ----------------------------------------------------------------------------------------
def cohort_cases(clean: pd.DataFrame) -> pd.DataFrame:
    from .rootcause import build_features

    f = build_features(clean)
    m = (f["status"] == "complete") & f["in_cohort"] & f["item_category"].isin(C.INVOICE_CATEGORIES)
    return f[m].copy()


def _capped_excess(cases: pd.DataFrame, flag: str, stage: str) -> pd.Series:
    """Per-case saving if ``flag`` were removed: case excess in ``stage`` over unflagged peers
    of the same category, capped at the category's median excess of the stage."""
    out = pd.Series(0.0, index=cases.index)
    for _, g in cases.groupby("item_category"):
        yes, no = g[g[flag]], g[~g[flag]]
        if len(yes) < 30 or len(no) < 30:
            continue
        peer = no[stage].median()
        cap = max(0.0, yes[stage].median() - peer)
        out.loc[yes.index] = (yes[stage] - peer).clip(lower=0, upper=cap).fillna(0)
    return out


def opportunity_savings(cases: pd.DataFrame) -> pd.DataFrame:
    """Return per-case potential savings (days) for each time-based opportunity, before the
    avoidable-share sampling."""
    rng = np.random.default_rng(SEED)
    s = pd.DataFrame(index=cases.index)

    def sample(mask: pd.Series, p: float) -> pd.Series:
        pick = pd.Series(rng.random(len(mask)) < p, index=mask.index)
        return mask & pick

    o1 = _capped_excess(cases, "payment_block", "match_to_clear_days")
    s["O1"] = o1.where(sample(cases["payment_block"], ASSUMPTIONS["O1"]["p_avoidable"]), 0.0)

    hot = (cases["n_vendor_items"] > 5000) & (cases["value"] < 500)
    peer = cases.loc[~hot, "match_to_clear_days"].median()
    s["O2"] = (cases["match_to_clear_days"] - peer).clip(lower=0).where(hot, 0.0).fillna(0)

    changed = cases["price_change"] | cases["quantity_change"]
    cases = cases.assign(changed=changed)
    o3 = _capped_excess(cases, "changed", "cycle_days")
    s["O3"] = o3.where(sample(changed, ASSUMPTIONS["O3"]["p_avoidable"]), 0.0)

    cap_excess = (cases["invoice_capture_days"] - TARGET_CAPTURE_DAYS).clip(lower=0)
    late = (cases["vci_to_clear_days"] - PAYMENT_TERM_DAYS).clip(lower=0)
    s["O4"] = np.minimum(cap_excess.fillna(0), late.fillna(0))

    o5 = _capped_excess(cases, "invoice_cancelled", "cycle_days")
    s["O5"] = o5.where(sample(cases["invoice_cancelled"], ASSUMPTIONS["O5"]["p_avoidable"]), 0.0)
    return s


def simulate(cases: pd.DataFrame, savings: pd.DataFrame) -> pd.Series:
    total = savings.sum(axis=1)
    floor = cases["po_to_gr_days"].fillna(0).clip(lower=0)
    return np.maximum(cases["cycle_days"] - total, floor)


# ----------------------------------------------------------------------------------------
def monthly_kpis(clean: pd.DataFrame, cases_all: pd.DataFrame) -> pd.DataFrame:
    """KPI values per PO-creation month (mature months only)."""
    c = cases_all.copy()
    c["month"] = c["po_month"]
    three_way = c["item_category"].isin([C.CAT_3W_AFTER, C.CAT_3W_BEFORE])
    c["first_pass_match"] = ~(c["payment_block"] | c["invoice_cancelled"])
    c["rework"] = c["price_change"] | c["quantity_change"] | c["invoice_cancelled"]
    c["on_time"] = c["vci_to_clear_days"] <= PAYMENT_TERM_DAYS
    g = c.groupby("month")
    k = pd.DataFrame(
        {
            "items": g.size(),
            "median_cycle_days": g["cycle_days"].median(),
            "p90_cycle_days": g["cycle_days"].quantile(0.9),
            "rework_rate": g["rework"].mean(),
            "first_pass_match_rate": c[three_way].groupby("month")["first_pass_match"].mean(),
            "three_way_items": c[three_way].groupby("month").size(),
            "on_time_payment_rate": g["on_time"].mean(),
            "on_time_items": g["on_time"].size(),
        }
    )
    return k.reset_index()


def plot_dashboard(k: pd.DataFrame, baseline: dict, target: dict, figures) -> None:
    fig, axes = viz.plt.subplots(2, 2, figsize=(11, 6.6))
    specs = [
        ("median_cycle_days", "Median cycle time (days)", "items", False),
        ("rework_rate", "Rework rate (%)", "items", True),
        ("first_pass_match_rate", "First-pass three-way match (%)", "three_way_items", True),
        (
            "on_time_payment_rate",
            f"Paid within {PAYMENT_TERM_DAYS} days of invoice (%)",
            "on_time_items",
            True,
        ),
    ]
    x = np.arange(len(k))
    for ax, (col, title, ncol, is_rate) in zip(axes.ravel(), specs, strict=True):
        scale = 100 if is_rate else 1
        y = k[col] * scale
        ax.plot(x, y, "-o", color=viz.SERIES[0], ms=5, mec=viz.SURFACE, mew=1.5, label="Actual")
        b = baseline[col] * scale
        ax.axhline(b, color=viz.INK_2, lw=1, ls="--")
        ax.text(len(k) - 0.6, b, " baseline", va="bottom", fontsize=8, color=viz.INK_2)
        t = target[col] * scale
        ax.axhline(t, color=viz.SERIES[2], lw=1.5)
        ax.text(len(k) - 0.6, t, " target", va="bottom", fontsize=8, color=viz.INK)
        if is_rate:
            # p-chart control limits around the baseline proportion
            p = baseline[col]
            sigma = np.sqrt(p * (1 - p) / k[ncol].clip(lower=1))
            ax.fill_between(
                x,
                100 * (p - 3 * sigma),
                100 * (p + 3 * sigma),
                color=viz.GRID,
                alpha=0.7,
                lw=0,
                label="3σ control limits",
            )
        ax.set_xticks(x, k["month"].str[2:], fontsize=8)
        ax.set_title(title, fontsize=10.5)
        ax.set_xlim(-0.5, len(k) + 0.9)
    axes[0, 0].set_ylim(bottom=0)
    fig.suptitle(
        "Control dashboard - baseline months (POs Jan-Aug 2018) against TO-BE targets",
        x=0.01,
        ha="left",
        fontsize=12,
        fontweight="bold",
        color=viz.INK,
    )
    viz.save(fig, figures / "kpi_dashboard.png")


def plot_priority(opps: pd.DataFrame, figures) -> None:
    effort_x = {"Low": 1, "Medium": 2, "High": 3}
    fig, ax = viz.plt.subplots(figsize=(8, 4.4))
    for r in opps.itertuples():
        xv = effort_x[r.effort] + (0.08 if r.id in ("O2", "O5") else -0.08 if r.id == "O4" else 0)
        yv = r.case_days_saved / 1000
        ax.scatter(
            xv,
            yv,
            s=110,
            color=viz.SERIES[1] if r.id != "O6" else viz.MUTED,
            edgecolor=viz.SURFACE,
            linewidth=2,
            zorder=3,
        )
        ax.annotate(
            f"{r.id} {r.short}",
            (xv, yv),
            xytext=(8, 4),
            textcoords="offset points",
            fontsize=8.5,
            color=viz.INK,
        )
    ax.set_xticks([1, 2, 3], ["Low", "Medium", "High"])
    ax.set_xlim(0.5, 3.9)
    ax.set_ylim(bottom=-max(1, opps["case_days_saved"].max() / 1000) * 0.05)
    ax.set_xlabel("Implementation effort (judgement)")
    ax.set_ylabel("Estimated waiting removed\n(thousand case-days, cohort)")
    ax.set_title("Prioritisation: impact from the data, effort from judgement")
    viz.save(fig, figures / "priority_matrix.png")


def write_tobe_bpmn(paths) -> None:
    import pm4py
    from pm4py.objects.process_tree.utils.generic import parse

    tree = parse(
        "->( X( 'Create purchase requisition', tau ), "
        "'Create PO from catalogue / contract price', "
        "+( 'Record goods receipt', ->( 'Receive e-invoice', 'Automatic three-way match' ) ), "
        "X( 'Auto-release for payment', ->( 'Resolve match exception (5-day SLA)', "
        "'Release for payment' ) ), 'Pay on due date' )"
    )
    bpmn = pm4py.convert_to_bpmn(tree)
    pm4py.write_bpmn(bpmn, str(paths.models / "to_be.bpmn"))
    pm4py.save_vis_bpmn(bpmn, str(paths.figures / "to_be_bpmn.png"))
    ers = parse(
        "->( 'Create PO from contract price', *( 'Record goods receipt', tau ), "
        "'Self-billing settlement (ERS) per period', 'Pay on due date' )"
    )
    pm4py.write_bpmn(pm4py.convert_to_bpmn(ers), str(paths.models / "to_be_ers_variant.bpmn"))


def run(clean: pd.DataFrame, paths) -> dict:
    out = paths.results / "tobe"
    out.mkdir(parents=True, exist_ok=True)
    cases = cohort_cases(clean)
    from .performance import case_table

    ct = case_table(clean[clean["case_id"].isin(cases.index)])
    cases["invoice_capture_days"] = ct["invoice_capture_days"]
    cases["ir_minus_gr_days"] = (ct["ir"] - ct["gr"]).dt.total_seconds() / 86400
    cases["vci_to_clear_days"] = (ct["clear"] - ct["vci"]).dt.total_seconds() / 86400
    cases["po_month"] = ct["po_month"]

    bands = pd.cut(
        cases["invoice_capture_days"],
        [-1, 2, 5, 10, 20, 40, 1000],
        labels=["0-2", "3-5", "6-10", "11-20", "21-40", ">40"],
    )
    ir_clear = cases["vci_to_clear_days"] - cases["invoice_capture_days"]
    anchor = (
        pd.DataFrame(
            {"band": bands, "vci_to_clear": cases["vci_to_clear_days"], "ir_to_clear": ir_clear}
        )
        .groupby("band", observed=True)
        .agg(
            items=("vci_to_clear", "size"),
            median_invoice_date_to_clear=("vci_to_clear", "median"),
            median_posting_to_clear=("ir_to_clear", "median"),
        )
    )
    anchor.reset_index().to_csv(
        out / "payment_anchor_evidence.csv", index=False, float_format="%.1f"
    )
    hot = (cases["n_vendor_items"] > 5000) & (cases["value"] < 500)
    hot_terms = {
        "hotspot_median_invoice_date_to_clear": float(cases.loc[hot, "vci_to_clear_days"].median()),
        "rest_median_invoice_date_to_clear": float(cases.loc[~hot, "vci_to_clear_days"].median()),
        "hotspot_items": int(hot.sum()),
    }
    savings = opportunity_savings(cases)
    new_cycle = simulate(cases, savings)

    from .conformance import rule_flags

    flags = rule_flags(clean[clean["status"] != "cancelled"])
    atf = flags["R6_after_the_fact_po"].fillna(False).astype(bool)
    atf_value = float(cases.loc[cases.index.intersection(atf[atf].index), "value"].sum())
    atf_n = int(cases.index.isin(atf[atf].index).sum())

    short = {
        "O1": "Auto-release matched invoices",
        "O2": "Self-billing for top vendors' small items",
        "O3": "Price/qty settled before PO",
        "O4": "E-invoicing",
        "O5": "Validate invoices at capture",
        "O6": "No PO, no pay",
    }
    rows = []
    for oid, a in ASSUMPTIONS.items():
        if oid in savings:
            sv = savings[oid]
            affected = int((sv > 0).sum())
            alone = simulate(cases, savings[[oid]])
            rows.append(
                {
                    "id": oid,
                    "short": short[oid],
                    "name": a["name"],
                    "items_improved": affected,
                    "case_days_saved": float(sv.sum()),
                    "median_saving_days": float(sv[sv > 0].median()) if affected else 0.0,
                    "median_cycle_if_alone": float(alone.median()),
                    "p90_cycle_if_alone": float(alone.quantile(0.9)),
                    "value_affected_eur": float(cases.loc[sv > 0, "value"].sum()),
                    "effort": a["effort"],
                    "kpi": a["kpi"],
                    "lever": a["lever"],
                    "assumption": a["assumption"],
                }
            )
        else:
            rows.append(
                {
                    "id": oid,
                    "short": short[oid],
                    "name": a["name"],
                    "items_improved": atf_n,
                    "case_days_saved": 0.0,
                    "median_saving_days": 0.0,
                    "median_cycle_if_alone": float(cases["cycle_days"].median()),
                    "p90_cycle_if_alone": float(cases["cycle_days"].quantile(0.9)),
                    "value_affected_eur": atf_value,
                    "effort": a["effort"],
                    "kpi": a["kpi"],
                    "lever": a["lever"],
                    "assumption": a["assumption"],
                }
            )
    opps = pd.DataFrame(rows)
    effort_score = opps["effort"].map({"Low": 1, "Medium": 2, "High": 3})
    opps["priority_score"] = opps["case_days_saved"] / effort_score
    opps = opps.sort_values(["priority_score", "value_affected_eur"], ascending=False)
    opps["priority"] = range(1, len(opps) + 1)
    opps.to_csv(out / "opportunities.csv", index=False, float_format="%.2f")
    plot_priority(opps, paths.figures)
    write_tobe_bpmn(paths)

    # KPIs: baseline on the cohort, target = simulated TO-BE values.
    base_cycle = float(cases["cycle_days"].median())
    k = monthly_kpis(clean, cases)
    k.to_csv(out / "kpi_monthly.csv", index=False, float_format="%.4f")
    three_way = cases["item_category"].isin([C.CAT_3W_AFTER, C.CAT_3W_BEFORE])
    fpm = ~(cases["payment_block"] | cases["invoice_cancelled"])
    rework = cases["price_change"] | cases["quantity_change"] | cases["invoice_cancelled"]
    on_time = cases["vci_to_clear_days"] <= PAYMENT_TERM_DAYS
    # TO-BE flags: avoided blocks / changes / cancellations are those that received a saving
    # or were sampled as avoidable.
    fpm_to = fpm | (savings["O1"] > 0) | (savings["O5"] > 0)
    rework_to = rework & ~((savings["O3"] > 0) | (savings["O5"] > 0))
    on_time_to = (cases["vci_to_clear_days"] - (cases["cycle_days"] - new_cycle)) <= (
        PAYMENT_TERM_DAYS
    )
    baseline = {
        "median_cycle_days": base_cycle,
        "rework_rate": float(rework.mean()),
        "first_pass_match_rate": float(fpm[three_way].mean()),
        "on_time_payment_rate": float(on_time[cases["vci_to_clear_days"].notna()].mean()),
        "p90_cycle_days": float(cases["cycle_days"].quantile(0.9)),
    }
    target = {
        "median_cycle_days": float(new_cycle.median()),
        "rework_rate": float(rework_to.mean()),
        "first_pass_match_rate": float(fpm_to[three_way].mean()),
        "on_time_payment_rate": float(on_time_to[cases["vci_to_clear_days"].notna()].mean()),
        "p90_cycle_days": float(new_cycle.quantile(0.9)),
    }
    plot_dashboard(k, baseline, target, paths.figures)
    on_time_sens = {
        str(d): float((cases["vci_to_clear_days"] <= d).mean()) for d in (30, 45, 60, 90)
    }
    summary = {
        "cohort_items": int(len(cases)),
        "cohort": [C.COHORT_START, C.COHORT_END],
        "payment_term_days_assumed": PAYMENT_TERM_DAYS,
        "baseline": baseline,
        "target": target,
        "combined_case_days_saved": float((cases["cycle_days"] - new_cycle).sum()),
        "sum_of_individual_case_days": float(savings.sum().sum()),
        "on_time_sensitivity": on_time_sens,
        "hotspot_payment_timing": hot_terms,
        "opportunities": opps.drop(columns=["lever", "assumption"]).to_dict("records"),
        "assumptions": ASSUMPTIONS,
    }
    (out / "tobe_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
