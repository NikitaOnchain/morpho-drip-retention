# Release Candidate Checklist

Status: **Phase 8 — CURRENT — reviewed release candidate ready for publication approval**. Local only; nothing pushed, published or sent.

## Accepted independent re-review — 4 September 2026

Verdict: **APPROVE WITH CAVEATS**, accepted by the project owner. See the [public evidence guide](../reviews/public/README.md), [portable re-review report](../reviews/public/REPORT.md), [verbatim verification summary](../reviews/public/verification_summary.json) and [original-to-public evidence manifest](../reviews/public/evidence_manifest.json). Original reviewer files remain unchanged. The report evaluates RC2 v2; final packaging preserves all reviewed calculation code, definitions, numerical CSVs and figures, with changes recorded in `release/finalization.json`.

| Finding | Status |
|---|---|
| R1 — code/evidence dependencies and portable provenance | CLOSED |
| R2 — 16 package-local broken links | CLOSED |
| R3 — explicit, tested reproduction levels | CLOSED |
| R4 — sparse post-period chart presentation | CLOSED |

Accepted caveats: full raw rebuild/new-DB logical reconciliation **NOT RUN**; public source-bundle acquisition **NOT AVAILABLE**; browser/GitHub rendering **NOT CHECKED**. Closing R1–R4 does not convert these into PASS. CSV-only is autonomous given the documented runtime/fonts; SQLite reproduction needs external inputs. The package is not self-contained for reconstruction from raw.

## Completed locally

- [x] Phase 7 acceptance and frozen presentation guardrail recorded.
- [x] English answer-first README, separate decision memo and six accepted figures assembled.
- [x] Headline provenance, reproduction guide and limitations documented.
- [x] Separate-code preflight matched 648 metric rows and 10,215 share reconciliations.
- [x] Isolated Phase 7 rerun matched five CSVs and six figures; original inputs/results unchanged.
- [x] Exact include/exclude inventory and redacted hygiene findings prepared; no files deleted.
- [x] Reviewer brief and pseudonymous distribution drafts prepared; no reviewer contacted.
- [x] Nine-page local Markdown build, six PNG embeddings, local-path links and syntax/data structure checks pass; browser-render limitation recorded.

## Required before a public release

- [x] Receive independent recalculation: numbers confirmed; verdict `CHANGES REQUESTED`.
- [x] Prepare mapped portable dependencies and two presentation derivatives, preserving originals.
- [x] Test CSV-only and accepted-SQLite routes with explicit IO roots; execute raw-preflight.
- [x] Obtain independent re-review of R1–R4 and accept remaining access/unrun-route limitations: APPROVE WITH CAVEATS.

- [x] Independent reviewer independently recomputes headline metrics from production evidence and returns a signed-off result with code/hashes; initial review plus targeted re-review retained.
- [x] Close R1–R4 and explicitly accept the documented reproduction/rendering caveats.
- [ ] Select the pseudonym, repository name/URL and license; review author/commit metadata for identity leakage.
- [x] Accept that public source-bundle access is unavailable for this v1 candidate. Full reproduction is not publicly accessible; any future bundle distribution requires separate privacy review and authorization.
- [x] Prepare tracked portable derivatives for required code/evidence; originals and frozen results preserved.
- [x] Resolve all 16 links and rerun checks against the actual staging package.
- [ ] Review the final renderer before publication or explicitly carry the accepted unverified-rendering caveat into publication approval. Browser/GitHub rendering is NOT CHECKED; static build and standalone PNG inspection are not browser signoff.
- [ ] Initialize/select the intended Git repository only with authorization, inspect staged files and Git history, and run a dedicated secret scanner before push. Current heuristic scan is not a guarantee.
- [ ] Confirm raw shards, SQLite, caches, credentials, local logs and temporary reproduction directories are not staged.
- [ ] Replace draft placeholders and check platform length/format and source links.
- [ ] Obtain explicit publication approval. Technical PASS and Phase 7 acceptance are not publishing authority.

## Phase gate

Phase 8 remains `CURRENT — reviewed release candidate ready for publication approval`. It is not complete. No GitHub push, external message, dashboard/app or public release was performed.
