import pandas as pd
import pytest

from p2pmining import config as C
from p2pmining import synthetic


@pytest.fixture(scope="session")
def synth() -> pd.DataFrame:
    return synthetic.generate(n_cases=400, seed=11)


@pytest.fixture()
def paths(tmp_path) -> C.OutputPaths:
    return C.OutputPaths(tmp_path).ensure()


def make_log(traces: dict[str, list[tuple[str, str]]], category: str = C.CAT_3W_AFTER):
    """Build a tiny canonical log from {case_id: [(activity, 'YYYY-MM-DD HH:MM'), ...]}."""
    rows = []
    for cid, events in traces.items():
        for i, (act, ts) in enumerate(events):
            rows.append(
                {
                    "event_id": f"{cid}-{i}",
                    "case_id": cid,
                    "activity": act,
                    "timestamp": pd.Timestamp(ts),
                    "user": "user_001",
                    "resource": "user_001",
                    "net_worth_eur": 100.0,
                    "item_category": category,
                    "spend_area": "Packaging",
                    "vendor": "vendorID_0001",
                    "document_type": "Standard PO",
                    "item_type": "Standard",
                    "company": "companyID_0000",
                    "sub_spend_area": "x",
                    "source_system": "s",
                    "spend_classification": "NPR",
                }
            )
    df = pd.DataFrame(rows)
    for col in df.columns:
        if col not in ("timestamp", "net_worth_eur"):
            df[col] = df[col].astype("string")
    df["timestamp"] = df["timestamp"].astype("datetime64[ns]")
    return df
