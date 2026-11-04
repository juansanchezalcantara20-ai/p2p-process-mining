# Purchase-to-pay process mining · committee summary

*Evidence base: the complete, public **BPI Challenge 2019** event log - real purchase-to-pay data from a multinational coatings and paints company, anonymised and published on 4TU.ResearchData - 1,595,923 events, 251,734
purchase-order items, 2018.*

## The problem

A purchase-order item takes a median of **80 days** from order to
payment, and one in ten takes more than **132 days**. Only
**43%** of invoices are paid within 60 days of their date
(assumed term), and **29%** of three-way-match items need
a manual intervention before they can be paid.

## The evidence

The process was reconstructed from system logs rather than interviews. After a documented
data-quality review ([1](01-data-quality.md)):

* **There is no single process.** 10,824 distinct paths; 42
  of them cover 80% of items, and only 61% of completed
  items follow the textbook flow ([2](02-discovery.md)).
* **Time is lost after the goods and the invoice are both in.** That last stage takes a median
  of 44 days - more than half of the cycle. One hand-over, *invoice receipt → clear*,
  holds 38% of all waiting time
  ([3](03-performance.md)).
* **Payment blocks are the costliest deviation.** 24% of invoice
  items were blocked; blocked items take a median 16 days longer than
  comparable unblocked ones. Overall 61% of completed items conform
  to the expected process ([4](04-conformance.md)).
* **A small group of vendors explains much of the tail.** Low-value items from the
  6 largest vendors (21,714 items, almost all Packaging) are slow
  64% of the time versus 19% for everything
  else; their extra time sits almost entirely after the invoice is matched ([5](05-root-cause.md)).
* **Payment is anchored on the vendor's invoice date**, not on when the invoice is posted - so
  faster invoice capture only helps invoices that are already late ([6](06-to-be.md)).

## Recommendation

Adopt the TO-BE process ([6](06-to-be.md)) - automatic three-way match with tolerance-based
release, e-invoicing, contract prices in the PO, self-billing for high-volume low-value lines
and "no PO, no pay" - in this order of priority:

| # | Lever | Estimated waiting removed (case-days, 8 months of orders) | Effort |
| --- | --- | --- | --- |
| 1 | Self-billing / consolidated invoicing for high-volume, low-value lines | 1,193,897 | Medium |
| 2 | E-invoicing to cut invoice capture time | 935,523 | Medium |
| 3 | Auto-release matched invoices (remove avoidable payment blocks) | 160,438 | Medium |
| 4 | Validate invoices at capture (fewer cancellations and re-postings) | 49,663 | Low |
| 5 | Settle price and quantity before the PO is issued | 112,543 | High |
| 6 | Enforce 'no PO, no pay' (after-the-fact purchasing) | 0 | Low |

If every lever delivers as assumed, the median cycle time would move from
**80 to about 63 days**, first-pass match
from 71% to 81%, and rework
from 14% to 9%. **These are estimates derived
from the 2018 data under written assumptions, not achieved savings.** Two decisions are needed
first: confirm the hotspot vendors' payment terms (it decides whether lever O2 is worth
anything) and replace the assumed 60-day term with real due dates.

Progress would be tracked monthly on the control dashboard ([7](07-dmaic.md)).

!!! info "How to read this site"
    Pages 1-7 follow the analysis in order. Every number is regenerated from the data by
    `make all`; every judgement call is in the [decision log](DECISIONS.md).
