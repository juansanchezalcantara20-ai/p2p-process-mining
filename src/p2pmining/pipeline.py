"""One command that reproduces every result: ``python -m p2pmining.pipeline --source full``.

Sources:
  full       the complete BPI Challenge 2019 log (downloaded on first run, ~37 MB zip)
  sample     the versioned 1% stratified sample in data/sample/ (used by CI)
  synthetic  a seeded synthetic P2P log with injected problems (Plan C / tests)
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd

from . import config as C
from . import ingest, quality, synthetic

log = logging.getLogger("p2pmining")

PHASES = ["quality", "discovery", "performance", "conformance", "rootcause", "tobe", "report"]


def load_source(source: str) -> tuple[pd.DataFrame, bool]:
    """Return (raw canonical log, whether to enforce the published fingerprint)."""
    if source == "full":
        raw_path = ingest.locate_raw()
        return ingest.load_cached(raw_path, C.DATA_INTERIM / "raw.parquet"), True
    if source == "sample":
        return ingest.read_raw(C.DATA_SAMPLE / "bpi2019_sample.csv.gz"), False
    if source == "synthetic":
        return synthetic.generate(n_cases=1500), False
    raise ValueError(f"Unknown source {source!r}")


def output_root(source: str, out: str | None) -> Path:
    if out:
        return Path(out)
    return C.ROOT if source == "full" else C.ROOT / "build" / source


def run(source: str = "full", phases: list[str] | None = None, out: str | None = None) -> dict:
    phases = phases or PHASES
    paths = C.OutputPaths(output_root(source, out)).ensure()
    timings: dict[str, float] = {}
    summary: dict = {"source": source}

    t0 = time.time()
    raw, check = load_source(source)
    clean = quality.run(raw, paths, check_fingerprint=check)
    del raw
    timings["quality"] = time.time() - t0

    # Later phases are imported lazily so that phase 1 stays usable on its own.
    for phase in phases:
        if phase == "quality":
            continue
        t0 = time.time()
        if phase == "discovery":
            from . import discovery

            summary["discovery"] = discovery.run(clean, paths)
        elif phase == "performance":
            from . import performance

            summary["performance"] = performance.run(clean, paths)
        elif phase == "conformance":
            from . import conformance

            summary["conformance"] = conformance.run(clean, paths)
        elif phase == "rootcause":
            from . import rootcause

            summary["rootcause"] = rootcause.run(clean, paths)
        elif phase == "tobe":
            from . import tobe

            summary["tobe"] = tobe.run(clean, paths)
        elif phase == "report":
            from . import report

            report.run(paths, source=source)
        timings[phase] = time.time() - t0
        log.info("phase %s done in %.1fs", phase, timings[phase])

    summary["timings_seconds"] = {k: round(v, 1) for k, v in timings.items()}
    (paths.results / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["full", "sample", "synthetic"], default="full")
    parser.add_argument("--phases", nargs="*", choices=PHASES, default=None)
    parser.add_argument("--out", default=None, help="Output root (default depends on source)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run(args.source, args.phases, args.out)


if __name__ == "__main__":
    main()
