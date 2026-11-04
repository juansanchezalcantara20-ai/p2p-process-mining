# Decision log

Every judgement call made while building this repository, with the reason behind it.
Newest phase last.

## Setup

| # | Decision | Why |
|---|---|---|
| D1 | **Dataset: BPI Challenge 2019 (Plan A), obtained from a public GitHub mirror of its CSV export**, not from 4TU directly. | The build environment's network policy blocked `data.4tu.nl` (HTTP 403 on CONNECT). A public mirror (`mrsonuk/BPI_Challenge_2019`) carries the CSV export. Authenticity is proven, not assumed: the loaded file matches the published fingerprint exactly (1,595,923 events, 251,734 cases) and the download is pinned by SHA-256. Anyone with access to 4TU can drop the official XES into `data/raw/` and the loader picks it up first. |
| D2 | Raw data is **never versioned**; `data/raw/` and `data/interim/` are git-ignored. | The zip is 37 MB and the CSV 527 MB. The pipeline downloads and verifies it on first run. |
| D3 | A **1% stratified sample** (by item category, whole cases, seed 42; 2,517 cases / 15,841 events, 432 KB) is versioned in `data/sample/`, in the original CSV layout and encoding. | Lets CI run the real ingestion path end-to-end in seconds, and lets a reader try the pipeline without downloading anything. Stratifying keeps the rare `2-way match` category represented. |
| D4 | **DuckDB for data-quality SQL, pandas for case-level feature engineering, pm4py for process-mining algorithms.** | DuckDB answers group-by questions over 1.6 M rows in seconds and the SQL is readable by analysts; pm4py is the reference open-source process-mining library. Polars was not needed once the log fit comfortably in memory (≈1.5 GB). |
| D5 | **One command reproduces everything** (`make all` → `python -m p2pmining.pipeline --source full` → `mkdocs build`). Every number in the report is rendered from `results/` by code. | No hand-typed figures that drift from the data. |
| D6 | Code licensed MIT. pm4py (AGPL-3.0) is used as an unmodified dependency, not redistributed. | Keeps the portfolio code reusable; pm4py's licence obligations attach to distributing pm4py itself. |
| D7 | Synthetic generator (`synthetic.py`) written as plain seeded simulation instead of pm4py play-out. | It is only the Plan C fallback and the unit-test fixture. Explicit simulation makes each injected problem (price-change rework, invoice before GR, payment blocks, approval bottleneck, after-the-fact invoices) a named, tunable parameter - which tests need as ground truth. Plan A succeeded, so the published analysis uses real data only. |

## Phase 1 · Data quality

| # | Decision | Why |
|---|---|---|
| Q1 | Decode the CSV as **Windows-1252**, not UTF-8. | 242 bytes `0x96` (an en dash, e.g. "Acrylic Resins – Liquid") make UTF-8 parsing fail; cp1252 decodes the file losslessly. |
| Q2 | **Case = purchase-order item** (`case concept:name`), as in the published log. | The P2P controls (match, receipt, invoice) operate at item level; a PO-header notion would merge independent items. |
| Q3 | **Drop whole cases with any timestamp outside 2017-01-01 - 2019-02-01** (88 cases, 3,081 events). | Dates such as 1948 or 2020 are entry errors. Dropping only the bad event would silently change that case's cycle time; dropping the case is cleaner and costs 0.03% of cases. |
| Q4 | **Collapse exact duplicate rows** (identical in every attribute except event ID; 132,721 rows after Q3). | They are bulk postings (mostly service-entry sheets) that add no timing or routing information but create artificial self-loops and thousands of spurious variants. The raw count is still reported. |
| Q5 | **Break same-timestamp ties with a canonical P2P position** (PR → PO → changes → vendor invoice → GR → IR → block removal → clear). | 18,294 cases contain ties, mostly because three activities are date-only (23:59 / 00:00). Without a rule the variant set would depend on file order. The rule is the least-assumption ordering; it never moves an event across a different timestamp. |
| Q6 | **Keep vendor invoices dated before the PO** (3,693 cases). | They are not data errors: they are evidence of after-the-fact purchasing, tested as a compliance rule in phase 4. |
| Q7 | **Case status: complete / open / cancelled.** Complete = reached *Clear Invoice* (consignment: a goods receipt, since consignment items are not invoiced per item); cancelled = deleted and never reactivated. | Measuring cycle time on open cases would understate it (right censoring). Performance and root cause use complete cases only. |
| Q8 | Normalise activity labels (whitespace, Title Case inside the *Change ...* family; prepositions such as "for" stay lower-case). | The source is consistent apart from *Change payment term*; the rule guards against a refreshed extract splitting one activity into two labels. |
| Q9 | Keep cases with missing spend area (3,289), labelled *Unknown*. | The attribute is descriptive; the events are valid. |
