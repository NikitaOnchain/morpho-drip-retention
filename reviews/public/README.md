# Independent re-review: accepted with caveats

The project owner accepted **APPROVE WITH CAVEATS** on 4 September 2026. **R1, R2, R3 and R4 are CLOSED.** This English guide is the maintainer's summary of the independent review, not a new independent assessment or publication authorization.

Primary evidence: [portable reviewer report, original Russian](REPORT.md), [verbatim verification summary](verification_summary.json), and [original-to-public evidence inventory](evidence_manifest.json). The original report is unchanged outside this package. Its public copy changes local links only and adds a portability notice; the inventory records both hashes and every link transformation. Omitted private execution receipts/scripts, database copies and source bundles are explicitly excluded, not silently claimed as packaged evidence.

## What was independently checked

| Finding | Result | Evidence |
|---|---|---|
| R1 — dependencies/provenance | CLOSED; 14 mapped derivatives verified; arithmetic changes not found | [Derivative checks](derivative_verification.json), [positive/negative contract cases](contract_checks.json) |
| R2 — package links | CLOSED; all 16 original defects resolved; 144 RC2-local links checked | [Static audit](static_audit.json), [review summary](verification_summary.json) |
| R3 — reproduction routes | CLOSED; CSV-only and accepted-SQLite routes actually run with separate declared inputs | [CSV QA](csv_qa.json), [SQLite route QA](sqlite_route_qa.json), [headline-check output](headline_review.json) |
| R4 — post-period charts | CLOSED; dense lines stop at campaign end, only three labeled post markers | [Standalone PNG inspection](visual_review.json) |

CSV-only reproduced **six of six PNGs**, with zero SQLite connections, network attempts or original-workspace reads. The separate SQLite-route used **two external files**; 648 metric rows and 10,215 share reconciliations had zero defects, and five CSVs/six PNGs matched. Its saved headline-check output is explicitly a same-author calculation path executed by the independent reviewer, not a new independent ABI replay. The initial independent numerical review is identified by hash in the verification summary.

The review evaluated RC2 v2: 170 files, 6,084,230 bytes; manifest SHA-256 `18bedd20ced80d229230214fd1170af1e35063330a017a7e07ca2ea48a99882a`. [Reviewed manifest](reviewed_package_manifest.json) retains that identity. Those are historical review counts, not the final package's size. Final package membership is in `release/manifest.json`; its documentation/evidence-only transition is recorded in `release/finalization.json`.

## Accepted caveats — not PASS

- Full raw → state rebuild and the new-database logical reconciliation were **NOT RUN**.
- Public source-bundle acquisition is **NOT AVAILABLE**. Hashes identify sources but do not make them accessible.
- Browser/GitHub/mobile rendering was **NOT CHECKED**. Standalone PNG inspection is not assembled-document render signoff.
- Cross-platform fonts and a fresh dependency installation were not tested. Heuristic secret screening is not a dedicated or Git-history audit.

The **CSV-only route is autonomous** with the stated Python/Pillow/fonts and included CSVs. The **SQLite-route needs external accepted production SQLite and metadata**. This is **not a self-contained raw-reconstruction package**. See [reproduction instructions](../../docs/REPRODUCTION.md) and [release checklist](../../docs/RELEASE_CHECKLIST.md).

All immutable reviewed metrics, SQL/calculation code, CSVs and figures retain their accepted identity. The 5.65M USDC and 4.14M USD₮0 are full P180 balances, not retained-uplift amounts or debt causally caused/preserved by DRIP. No new causal claim, RPC/GBA query, push, public upload or draft sending accompanies acceptance.
