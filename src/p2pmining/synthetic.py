"""Synthetic purchase-to-pay log (Plan C and test fixture).

Generates cases in the same canonical schema as the real log, with a fixed seed and known,
injected problems so that every phase can be tested against ground truth:

* rework through price changes after the PO (``p_price_change``);
* invoices posted before goods receipt in 'invoice after GR' items (``p_invoice_before_gr``);
* payment blocks that delay clearing (``p_payment_block``);
* an approval bottleneck for one spend area (``slow_spend_area``);
* vendor invoices dated before the PO exists - "after-the-fact" buying (``p_after_the_fact``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

SPEND_AREAS = ["Packaging", "Sales", "Logistics", "Additives", "CAPEX & SOCS"]
CATEGORY_WEIGHTS = {
    C.CAT_3W_BEFORE: 0.80,
    C.CAT_3W_AFTER: 0.10,
    C.CAT_CONSIGNMENT: 0.07,
    C.CAT_2W: 0.03,
}


def generate(
    n_cases: int = 600,
    seed: int = 7,
    p_price_change: float = 0.15,
    p_invoice_before_gr: float = 0.30,
    p_payment_block: float = 0.20,
    p_after_the_fact: float = 0.05,
    slow_spend_area: str = "CAPEX & SOCS",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cats = list(CATEGORY_WEIGHTS)
    rows: list[dict] = []
    start = pd.Timestamp("2018-01-02")
    eid = 0
    for i in range(n_cases):
        cat = cats[rng.choice(len(cats), p=list(CATEGORY_WEIGHTS.values()))]
        area = SPEND_AREAS[rng.integers(len(SPEND_AREAS))]
        vendor = f"vendorID_{rng.integers(30):04d}"
        value = float(np.round(rng.lognormal(6, 1.2), 2))
        attrs = {
            "case_id": f"45000{i:05d}_00010",
            "spend_area": area,
            "company": "companyID_0000",
            "document_type": "Standard PO",
            "sub_spend_area": area + " sub",
            "purchasing_document": f"45000{i:05d}",
            "purch_doc_category": "Purchase order",
            "vendor": vendor,
            "item_type": "Consignment" if cat == C.CAT_CONSIGNMENT else "Standard",
            "item_category": cat,
            "spend_classification": "NPR",
            "source_system": "sourceSystemID_0000",
            "vendor_name": vendor.replace("ID", ""),
            "gr_based_inv_verif": str(cat == C.CAT_3W_AFTER).lower(),
            "item": "00010",
            "goods_receipt_flag": str(cat != C.CAT_2W).lower(),
        }
        t = start + pd.Timedelta(days=float(rng.uniform(0, 300)), hours=float(rng.uniform(8, 17)))
        trace: list[tuple[str, pd.Timestamp]] = []

        def add(act: str, gap_days: float, trace=trace) -> None:
            nonlocal t
            t = t + pd.Timedelta(days=gap_days)
            trace.append((act, t))

        has_pr = rng.random() < 0.3
        if has_pr:
            add(C.PR, 0)
        after_fact = rng.random() < p_after_the_fact and cat != C.CAT_CONSIGNMENT
        if after_fact:
            add(C.VCI, 0)
        approval = rng.exponential(25 if area == slow_spend_area else 1.5)
        add(C.PO, approval if has_pr else (0 if not after_fact else 3))
        if rng.random() < p_price_change:
            add(C.CHANGE_PRICE, rng.exponential(4))
        if cat == C.CAT_CONSIGNMENT:
            add(C.GR, rng.exponential(10))
        elif cat == C.CAT_2W:
            if not after_fact:
                add(C.VCI, rng.exponential(10))
            add(C.IR, rng.exponential(5))
            add(C.CLEAR, rng.exponential(20))
        else:
            inv_first = cat == C.CAT_3W_BEFORE or rng.random() < p_invoice_before_gr
            if not after_fact:
                add(C.VCI, rng.exponential(8))
            if inv_first:
                add(C.IR, rng.exponential(3))
                add(C.GR, rng.exponential(10))
            else:
                add(C.GR, rng.exponential(10))
                add(C.IR, rng.exponential(3))
            if rng.random() < p_payment_block:
                add(C.REMOVE_BLOCK, rng.exponential(25))
            add(C.CLEAR, rng.exponential(15))
        open_case = rng.random() < 0.08
        if open_case:
            trace = trace[:-1] or trace
        for act, ts in trace:
            eid += 1
            rows.append(
                {
                    **attrs,
                    "event_id": str(eid),
                    "activity": act,
                    "timestamp": ts.floor("min"),
                    "user": f"user_{rng.integers(20):03d}",
                    "resource": None,
                    "net_worth_eur": value,
                }
            )
    df = pd.DataFrame(rows)
    df["resource"] = df["user"]
    for col in df.columns:
        if col not in ("timestamp", "net_worth_eur"):
            df[col] = df[col].astype("string")
    df["timestamp"] = df["timestamp"].astype("datetime64[ns]")
    return df
