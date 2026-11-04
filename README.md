# Purchase-to-pay process mining on real data (BPI Challenge 2019)

Discovering the real purchase-to-pay process from event data instead of interviews:
data quality, AS-IS discovery, bottlenecks, conformance, root cause and a quantified TO-BE.

> **Status:** phase 1 (data quality) complete. Further phases are added incrementally.

## Run it

```bash
make install
make all        # downloads the log (~37 MB), runs every phase, builds the report site
make sample     # same pipeline on the versioned 1% sample, in seconds
make test lint
```

See [`docs/DECISIONS.md`](docs/DECISIONS.md) for every judgement call and why.
