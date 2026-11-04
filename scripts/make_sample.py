"""Build the small, versioned sample of the raw log (stratified by item category).

Usage: python scripts/make_sample.py [fraction]

The sample keeps whole cases (never single events), draws the same fraction from each item
category with a fixed seed, and is written in the original CSV layout and encoding so that
the pipeline exercises exactly the same ingestion path as for the full log.
"""

from __future__ import annotations

import gzip
import io
import sys
import zipfile

import numpy as np
import pandas as pd

from p2pmining import config as C
from p2pmining import ingest

SEED = 42


def main(fraction: float = 0.01) -> None:
    path = ingest.locate_raw()
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw = zf.read(name)
    df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding=C.SOURCE_ENCODING, keep_default_na=False)
    cases = df.drop_duplicates("case concept:name")[["case concept:name", "case Item Category"]]
    rng = np.random.default_rng(SEED)
    keep = []
    for _, grp in cases.groupby("case Item Category"):
        n = max(5, round(len(grp) * fraction))
        keep.extend(rng.choice(grp["case concept:name"].to_numpy(), size=n, replace=False))
    sample = df[df["case concept:name"].isin(set(keep))]
    C.DATA_SAMPLE.mkdir(parents=True, exist_ok=True)
    out = C.DATA_SAMPLE / "bpi2019_sample.csv.gz"
    buf = sample.to_csv(index=False, encoding=C.SOURCE_ENCODING).encode(C.SOURCE_ENCODING)
    out.write_bytes(gzip.compress(buf, mtime=0))
    print(f"{out}: {sample['case concept:name'].nunique()} cases, {len(sample)} events")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 0.01)
