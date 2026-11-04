"""Phase 1a - acquire and load the event log into a canonical pandas schema.

Resolution order for the raw data (first hit wins):

1. an official XES or CSV file the user placed in ``data/raw/`` (downloaded from 4TU);
2. the public mirror zip already in ``data/raw/``;
3. a fresh download of the mirror, verified against a pinned SHA-256.

Whatever the source, the loaded log must match the published fingerprint (event and case
counts) before any analysis runs - see :mod:`p2pmining.quality`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from . import config as C

log = logging.getLogger(__name__)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_mirror(dest_dir: Path = C.DATA_RAW) -> Path:
    """Download the mirror zip and verify its checksum."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / C.MIRROR_FILENAME
    if dest.exists() and sha256(dest) == C.MIRROR_SHA256:
        return dest
    log.info("Downloading BPI Challenge 2019 mirror from %s", C.MIRROR_URL)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(C.MIRROR_URL, tmp)  # noqa: S310 - pinned https URL
    digest = sha256(tmp)
    if digest != C.MIRROR_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for mirror download: {digest}")
    tmp.rename(dest)
    return dest


def locate_raw(raw_dir: Path = C.DATA_RAW) -> Path:
    """Return the best available raw file, downloading the mirror if nothing is present."""
    for pattern in ("*.xes", "*.xes.gz", "BPI_Challenge_2019*.csv"):
        hits = sorted(raw_dir.glob(pattern))
        if hits:
            return hits[0]
    mirror = raw_dir / C.MIRROR_FILENAME
    if mirror.exists():
        return mirror
    return download_mirror(raw_dir)


def _canonicalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in C.COLUMN_MAP.items() if k in df.columns})
    missing = {"case_id", "activity", "timestamp"} - set(df.columns)
    if missing:
        raise ValueError(f"Event log is missing required columns: {sorted(missing)}")
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], format="%d-%m-%Y %H:%M:%S.%f", errors="coerce"
        )
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df["timestamp"] = df["timestamp"].astype("datetime64[ns]")
    if "net_worth_eur" in df.columns:
        df["net_worth_eur"] = pd.to_numeric(df["net_worth_eur"], errors="coerce")
    for col in df.columns:
        if col not in ("timestamp", "net_worth_eur"):
            df[col] = df[col].astype("string")
    return df


def read_csv_bytes(raw: bytes, encoding: str = C.SOURCE_ENCODING) -> pd.DataFrame:
    """Parse the CSV export. The file is Windows-1252 encoded (not UTF-8)."""
    text = raw.decode(encoding)
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""])


def read_raw(path: Path) -> pd.DataFrame:
    """Load a raw file (mirror zip, CSV or XES) into the canonical schema."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            df = read_csv_bytes(zf.read(name))
    elif suffixes.endswith(".csv"):
        df = read_csv_bytes(path.read_bytes())
    elif suffixes.endswith(".csv.gz"):
        import gzip

        df = read_csv_bytes(gzip.decompress(path.read_bytes()))
    elif ".xes" in suffixes:
        import pm4py

        df = pm4py.read_xes(str(path))
        # XES attribute keys map onto the CSV header ("case:X" -> "case X", "X" -> "event X").
        ren = {}
        for col in df.columns:
            if col.startswith("case:"):
                ren[col] = "case " + col[len("case:") :]
            elif col != "eventID":
                ren[col] = "event " + col
        df = df.rename(columns=ren)
    else:
        raise ValueError(f"Unsupported raw file: {path}")
    return _canonicalise(df)


def load_cached(path: Path, cache: Path) -> pd.DataFrame:
    """Read the raw log once and cache it as parquet for fast re-runs."""
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return pd.read_parquet(cache)
    df = read_raw(path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df
