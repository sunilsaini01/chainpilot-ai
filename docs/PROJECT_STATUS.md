# Project Status

Current phase: P8 (AWS), demo days only, ap-south-1 (D-063)
Current task: P8-T3, staging deployment (done: https://d3ry42c2brz8fx.cloudfront.net; deploys from GitHub)
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 5fe9f46 (CI #34 green, P8-T1).

## P8-T1 acceptance criteria
- [x] Terraform for bootstrap (state bucket, GitHub OIDC role, budget) and staging (network, ECR, RDS, ECS + ALB, S3 + CloudFront, secrets, alarms)
- [x] No secret values in files or state (RDS-managed password; the Groq key is filled in by the owner)
- [x] `fmt` and `validate` pass for both folders, from a clean state with the lock files; a CI job runs them
- [x] Cost table updated (x86; ap-south-1)
- [ ] CI green on GitHub. NOT VERIFIED: requires a push
- Not possible offline: plan/apply (P8-T3). Nothing has been created in AWS.

Open findings: P8-T1-R1 (MEDIUM, P8-T3), P8-T1-R2 (MEDIUM), P8-T1-R3/R4/R5 (LOW, P8-T3), P7-T3-R1 (LOW, solved by the P8 design once deployed), P7-T3-R2 (LOW), P7-T1-R1 (LOW, mitigated), P6-T4-R3 (LOW, P9), P6-T4-R4 (LOW, solved by the P8 design once deployed), P6-T2-R1 (LOW), P6-T1b-R1 (LOW), P5-T4-R7 (MEDIUM), P5-T4-R6 (MEDIUM), P5-T4-R4 (LOW), P5-T4-R5 (owner), P4-T4-R3 (LOW), P4-T3-R3 (LOW, partly fixed), P3-T3-R3 (LOW), P3-T2b-R2 (LOW). See docs/REVIEW_QUEUE.md.
Next action: Owner checks and pushes; then P8-T2 (account setup with the bootstrap folder, owner-run).
Blockers: P8-T2 onwards needs the owner at their AWS account (AWS CLI install, credentials, approval of each apply).

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
| P5-T4 Grounding, tool and safety evaluation | APPROVED (CI #25; run 1 gate passed, run 2 not; R6/R7 left open by the owner) |
| P6-T1 Web app foundation, login, overview | APPROVED (CI #26 green on c0cb7db) |
| P6-T1b User accounts in the dashboard (Users page, My account) | APPROVED (CI #26 green on c0cb7db) |
| P6-T2 Risk, recommendation, supplier, forecast and delivery-risk screens | APPROVED (CI #27 green on 2106dcb) |
| P6-T3 Copilot view and audit timeline (approval queue moved to P7) | APPROVED (CI #28 green on 7164f10) |
| P6-T4 Browser end-to-end tests, error/empty states, accessibility, Compose | APPROVED (CI #29 green on 835a6d5) |
| P7-T1 Approval workflow in the API (decide, execute, idempotency, concurrency, audit) | APPROVED (CI #30 green on ce3de6c) |
| P7-T2 Approval queue screen with browser tests | APPROVED (CI #31 green on f70d33d) |
| P7-T3 Login token in an httpOnly cookie with CSRF protection | APPROVED (CI #32 green on 46135fe) |
| P7-T4 Security sweep: every write endpoint against every role; API security headers | APPROVED (CI #33 green on 6ebb899) |
| P8-T1 Terraform for staging, checked offline (no AWS) | APPROVED (CI #34 green on 5fe9f46) |
| P8-T2 AWS account setup: budget, state bucket, GitHub OIDC role | APPROVED (verified in AWS) |
| P8-T3 Plan → review → apply staging; deploy workflow; smoke tests | APPROVED (CI #39 green on 3f3cb80) |
| P8-T4 Rollback drill, alarms, dashboard, destroy/pause instructions | APPROVED (alarm emails confirmed by the owner) |
| P9-T1 Load test and security scans | APPROVED (CI #43 green on 6efa467) |
| P9-T2 Demo setup and demo script | APPROVED (CI #44 green on a6f88df) |
| P9-T3 Final README, architecture diagram, limitations | READY_FOR_USER_CHECK (links and numbers checked by script; diagrams to check on GitHub) |
| P9-T4 Acceptance checklist with evidence | NOT_STARTED |
| P9-T5 Manual walkthrough (keyboard, screen reader) and final full run | NOT_STARTED |

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
- 2026-10-17: P5 closed (CI #25). P6 started: web app foundation, login and overview.
- 2026-10-17: P6-T1b: admins manage accounts in the dashboard; users change their own password.
- 2026-10-17: P6-T2: five data screens in the dashboard.
- 2026-10-17: P6-T3: copilot screen and audit log in the dashboard.
- 2026-10-17: P6-T4: browser tests and accessibility checks in CI; the dashboard in Docker Compose.
- 2026-10-17: P6 complete (CI #29). P7-T1: managers approve or reject recommendations; approved ones become purchase orders or stock transfers.
- 2026-10-17: P7-T2: the approval queue in the dashboard; approvals tested end to end in a browser.
- 2026-10-17: P7-T3: the dashboard's login is an httpOnly cookie with CSRF protection.
- 2026-10-17: P7-T4: every endpoint checked against every role; security headers on the API and the dashboard.
- 2026-10-17: P7 complete (CI #33). P8 plan and cost estimate written; waiting for the owner's approval before any AWS action.
- 2026-10-17: P8 approved for demo days only (ap-south-1). P8-T1: Terraform for staging written and validated offline; nothing deployed.
