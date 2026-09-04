# Figures

Store final reproducible charts and any lightweight figure metadata here.

Every chart should have a clear question, unit, population, time window, source note and a link to the producing SQL or transformation. Prefer neutral descriptive titles until the finding is validated.

## Phase 7 figures

All six PNGs are produced by `scripts/analyze_phase7_metrics.py` from the
accepted Phase 6 SQLite and exact boundary map. Their chart contracts and
visual QA are recorded in `docs/PHASE7_ANALYSIS_QA.md`.

- `phase7_borrowed_assets_checkpoints.png`: separate USDC and USD₮0 outstanding-debt series through P180.
- `phase7_retained_uplift.png`: primary campaign-end retained uplift and separately labeled peak sensitivity.
- `phase7_debt_flow_decomposition.png`: gross borrow, repay, interest, liquidation and observed debt change.
- `phase7_market_concentration.png`: market-level top shares at campaign end and P180.
- `phase7_archetype_borrowed_assets.png`: native-unit borrowed assets and collateral for the three precommitted archetypes.
- `phase7_active_borrowers.png`: primary material active borrowers and the positive-shares dust sensitivity.
