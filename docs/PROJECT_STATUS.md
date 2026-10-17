# Project Status

Current phase: P5 (AI copilot)
Current task: P5-T4, copilot evaluation (two real runs done)
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 099f3ab (CI #22 green). The provider switch (D-052) and P5-T4 are uncommitted.

## P5-T4 acceptance criteria
- [x] 14 pre-registered cases (7 answerable, 7 safety) and pass thresholds, fixed before any run
- [x] Checks: grounding, expected citations, unsupported numbers, refusal, injection, key leak, exact database-change check
- [x] The checks themselves tested with scripted good and bad models; 13/13 mutations caught
- [x] Dry run on the real demo data with a fake model: expected answers computed correctly; no provider called
- [x] Real run with the owner's permission: Groq `qwen/qwen3.8-27b` 12/14, gate PASSED (configured Groq model retired; Gemini project denied by Google)
- [x] Request-size fix (P5-T4-R3) and a second run: 12/14, gate NOT passed (one 429 rate limit; tool messages listed as citations, removed by verification)
- [ ] CI green on GitHub. NOT VERIFIED: requires a push

P5 gate ("grounded output; tool and safety evaluation"): passed in run 1, not repeated in run 2; open: P5-T4-R6 (rate limits), P5-T4-R7 (citation format).

Open findings: P5-T4-R7 (MEDIUM), P5-T4-R6 (MEDIUM), P5-T4-R4 (LOW, documented), P5-T4-R5 (owner: model name and Gemini key), P4-T4-R3 (LOW, documented), P4-T3-R3 (LOW, P7), P3-T3-R3 (LOW, documented), P3-T2b-R2 (LOW, documented). See docs/REVIEW_QUEUE.md.
Next action: Owner pushes; decides: fix P5-T4-R7/R6 and run a third time, or move on to P6 with them open.
Blockers: none.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles (+ audit, rate limiting) | APPROVED (owner, 2026-10-15; CI #3 green on 51b9039) |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | APPROVED (owner, 2026-10-15; CI #4 green on 92b4793) |
| P1-T4 Deterministic synthetic seed data | APPROVED (owner, 2026-10-15; CI #5 green on 9d9798c) |
| P2-T1 M5 loader, validation, fixtures, download guide | APPROVED (owner, 2026-10-15; CI #7 green on a5ad708) |
| P2-T2 Features, baselines, rolling-origin backtests, metrics | APPROVED (owner, 2026-10-15; CI #8 green on f5601f9) |
| P2-T3 LightGBM model, uncertainty, artifacts | APPROVED as first version (owner, 2026-10-15; CI #9 green on 7ead45b) |
| P2-T3b Improved model: validation period, weekly models, calibrated intervals | APPROVED (owner, 2026-10-16; CI #10 green on 0c32413) |
| P2-T4 Forecast tables, import and API | APPROVED (CI #11 green on 8c07d78; P2 complete) |
| P3-T1 Olist loader, label, dispatch features, split | APPROVED (pushed 0b891fb; CI #12) |
| P3-T2 Delivery-risk models (logistic baseline, tree), calibration | APPROVED as first experiment (CI #13 green on 66a6915) |
| P3-T2b Rolling monthly evaluation, recent calibration | APPROVED (CI #14 green on 3f32f42) |
| P3-T3 Delivery-risk scores in the API | APPROVED (CI #15 green on ba3a841; P3 complete) |
| P4-T1 Inventory policy math | APPROVED (CI #16 green on 154eafb) |
| P4-T2 Replay simulator vs simple reorder baseline | APPROVED (CI #17 green on ae39d72) |
| P4-T3 Suppliers, purchase orders, lead times (DB + seed) | APPROVED (CI #18 green on 7c52c18) |
| P4-T4 Stock-out risks and recommendations API | APPROVED (CI #19 green on 2f28e04; P4 complete) |
| P5-T1 Policy documents and retrieval | APPROVED (CI #20 green on 988d83e) |
| P5-T2 Typed read-only tools with citations | APPROVED (CI #21 green on 69d4f77) |
| P5-T3 LangGraph supervisor (Groq or Gemini) | READY_FOR_USER_CHECK (real-model check waits for a key) |
| P5-T4 Grounding, tool and safety evaluation | READY_FOR_USER_CHECK (run 1 gate passed, run 2 not) |
| P6–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit. Owner pushed c997ed9; CI #2 green; P1-T1 approved.
- 2026-10-15: P1-T2 built and self-reviewed; at the owner's request the review queue was cleared before commit (migration 0004). Owner pushed 51b9039; CI #3 green; P1-T2 approved.
- 2026-10-15: P1-T3 built and self-reviewed (migration 0005); review queue cleared before commit. Owner pushed d614e58, 7d4e841, 92b4793; CI #4 green; P1-T3 approved.
- 2026-10-15: P1-T4 built and self-reviewed; P1 gate met locally. Owner pushed 528ae5e, ca0d17c, 9d9798c; CI #5 green; P1 complete.
- 2026-10-15: P2 started. P2-T1 built (no real data needed); P2-T2 blocked until M5 is downloaded.
- 2026-10-15: owner downloaded M5; real data validated; long-table memory fixed (one store 3.5 GB to 179 MB).
- 2026-10-15: P2-T2 built; first real baseline results on all 10 M5 stores (docs/MODEL_RESULTS.md).
- 2026-10-15: P2-T3 built; LightGBM evaluated honestly (ties/loses to the 28-day moving average); artifacts pipeline works.
- 2026-10-16: P2-T3b: weekly LightGBM chosen on validation; beats the moving average on the test windows; intervals calibrated.
- 2026-10-16: P2-T4 built (publish, import, API, holdout check); review fixes for P2-T2-R2/R3.
- 2026-10-16: P2 complete (CI #11). P3 started: Olist downloaded; P3-T1 built.
- 2026-10-16: P3-T2 first experiment: ranking good, calibration and model choice unstable across periods.
- 2026-10-16: P3-T2b: rolling monthly evaluation; logistic regression + recent Platt chosen; calibration much improved; rank-first serving recommended.
- 2026-10-16: P3-T3: delivery-risk scores published (daily tiers with reasons), imported and served under /delivery-risk; tiers checked on real outcomes.
- 2026-10-16: P3 complete (CI #15). Import hardening for both imports (P3-T3-R4).
- 2026-10-16: P4 started (D-044); P4-T1 policy math built.
- 2026-10-16: P4-T2: replay on real demand; the forecast-driven policy needs 17–34% less stock than a simple reorder rule at the same fill rate.
- 2026-10-16: P4-T3: suppliers, purchasing rules and purchase orders (seeded history; receive through the ledger).
- 2026-10-16: P4-T4: stock-out risks and transfer/reorder recommendations (proposals); P4 gate met locally.
- 2026-10-17: P4 complete (CI #19). P5 started; P5-T1 policy documents and search.
- 2026-10-17: OpenAI chosen for the copilot (gpt-5.4-mini). P5-T2: seven read-only tools with citations; supplier ratings; seed delivery history fixed.
- 2026-10-17: P5-T3: LangGraph copilot built and tested with a scripted model; first real OpenAI calls refused for lack of credits (nothing charged).
- 2026-10-17: copilot provider switched from OpenAI to Groq and Gemini (D-052).
- 2026-10-17: P5-T4 evaluation built and dry-run on real data; no provider call made.
- 2026-10-17: first real copilot evaluation: Groq qwen3.8-27b 12/14, gate passed; P5 gate met.
- 2026-10-17: request-size fix; second Groq run 12/14, gate not passed (rate limit, citation format).
