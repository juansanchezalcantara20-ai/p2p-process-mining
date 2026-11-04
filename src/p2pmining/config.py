"""Paths, constants and domain vocabulary shared by every phase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_SAMPLE = ROOT / "data" / "sample"

# --- Source dataset -------------------------------------------------------------------------
# Official publication: van Dongen, B.F. (2019). BPI Challenge 2019. 4TU.ResearchData.
DATASET_DOI = "10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1"
DATASET_LANDING = f"https://doi.org/{DATASET_DOI}"
# Public mirror of the CSV export of the same log (used when 4TU is unreachable).
MIRROR_URL = (
    "https://raw.githubusercontent.com/mrsonuk/BPI_Challenge_2019/master/"
    "Dataset/BPIChallenge2019_Original.zip"
)
MIRROR_SHA256 = "372b5a15c30f4a21b370db25b1912cc60ad1104d4198cfd34f8aecb2f4c2425a"
MIRROR_FILENAME = "BPIChallenge2019_mirror.zip"
# Fingerprint published with the log; used to prove the mirror is the genuine dataset.
PUBLISHED_EVENTS = 1_595_923
PUBLISHED_CASES = 251_734
SOURCE_ENCODING = "cp1252"

# --- Observation window -----------------------------------------------------------------------
# The log covers purchase orders created in 2018; extraction happened in early 2019.
WINDOW_START = "2017-01-01"
WINDOW_END = "2019-02-01"
# Mature cohort for duration measures: POs created Jan-Aug 2018. At least ~89% of these items
# had finished by extraction; later cohorts are dominated by unfinished items, so their
# "complete" cases are only the fast ones (right censoring).
COHORT_START = "2018-01-01"
COHORT_END = "2018-09-01"

# --- Column mapping (raw CSV header -> canonical snake_case) --------------------------------
COLUMN_MAP = {
    "eventID": "event_id",
    "eventID ": "event_id",
    "case concept:name": "case_id",
    "event concept:name": "activity",
    "event time:timestamp": "timestamp",
    "event User": "user",
    "event org:resource": "resource",
    "event Cumulative net worth (EUR)": "net_worth_eur",
    "case Spend area text": "spend_area",
    "case Company": "company",
    "case Document Type": "document_type",
    "case Sub spend area text": "sub_spend_area",
    "case Purchasing Document": "purchasing_document",
    "case Purch. Doc. Category name": "purch_doc_category",
    "case Vendor": "vendor",
    "case Item Type": "item_type",
    "case Item Category": "item_category",
    "case Spend classification text": "spend_classification",
    "case Source": "source_system",
    "case Name": "vendor_name",
    "case GR-Based Inv. Verif.": "gr_based_inv_verif",
    "case Item": "item",
    "case Goods Receipt": "goods_receipt_flag",
}

CASE_ATTRIBUTES = [
    "spend_area",
    "company",
    "document_type",
    "sub_spend_area",
    "purchasing_document",
    "purch_doc_category",
    "vendor",
    "item_type",
    "item_category",
    "spend_classification",
    "source_system",
    "vendor_name",
    "gr_based_inv_verif",
    "item",
    "goods_receipt_flag",
]

# --- Domain vocabulary ------------------------------------------------------------------------
PR = "Create Purchase Requisition Item"
PO = "Create Purchase Order Item"
GR = "Record Goods Receipt"
IR = "Record Invoice Receipt"
VCI = "Vendor creates invoice"
CLEAR = "Clear Invoice"
SES = "Record Service Entry Sheet"
CHANGE_PRICE = "Change Price"
CHANGE_QTY = "Change Quantity"
REMOVE_BLOCK = "Remove Payment Block"
SET_BLOCK = "Set Payment Block"
DELETE_ITEM = "Delete Purchase Order Item"
REACTIVATE_ITEM = "Reactivate Purchase Order Item"
CHANGE_APPROVAL = "Change Approval for Purchase Order"

CAT_3W_AFTER = "3-way match, invoice after GR"
CAT_3W_BEFORE = "3-way match, invoice before GR"
CAT_2W = "2-way match"
CAT_CONSIGNMENT = "Consignment"
INVOICE_CATEGORIES = (CAT_3W_AFTER, CAT_3W_BEFORE, CAT_2W)
ITEM_CATEGORIES = (CAT_3W_BEFORE, CAT_3W_AFTER, CAT_CONSIGNMENT, CAT_2W)

# Canonical position of each activity in a "textbook" P2P flow. Used only to break ties
# between events that carry the same timestamp (date-only events are common in this log).
ACTIVITY_RANK = {
    "SRM: Created": 1,
    "SRM: Complete": 2,
    "SRM: Awaiting Approval": 3,
    "SRM: Document Completed": 4,
    "SRM: In Transfer to Execution Syst.": 5,
    "SRM: Ordered": 6,
    "SRM: Change was Transmitted": 7,
    PR: 10,
    "Release Purchase Requisition": 11,
    PO: 20,
    "Release Purchase Order": 21,
    CHANGE_APPROVAL: 22,
    "Receive Order Confirmation": 25,
    "Update Order Confirmation": 26,
    CHANGE_PRICE: 30,
    CHANGE_QTY: 31,
    VCI: 40,
    "Vendor creates debit memo": 41,
    GR: 50,
    SES: 51,
    IR: 60,
    "Record Subsequent Invoice": 61,
    SET_BLOCK: 65,
    REMOVE_BLOCK: 70,
    CLEAR: 80,
}
DEFAULT_RANK = 55


@dataclass(frozen=True)
class OutputPaths:
    """Where one pipeline run writes its artefacts.

    The full run writes into the versioned ``results/`` and ``docs/`` folders; sample and
    synthetic runs write under ``build/<name>/`` so they never overwrite published results.
    """

    root: Path

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def figures(self) -> Path:
        return self.root / "docs" / "assets" / "figures"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    def ensure(self) -> OutputPaths:
        for p in (self.results, self.figures, self.models, self.docs):
            p.mkdir(parents=True, exist_ok=True)
        return self
