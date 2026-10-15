# ChainPilot AI — Claude Code Only: Project & Execution Workflow

> Version 1.0 | Owner: student developer | Execution agent: Claude Code only | No Codex, Kafka, or Kubernetes.

## 0. Read this first — migration from the two-agent workflow
This document replaces the Claude↔Codex role-swapping and review protocol. Preserve all existing application code, Git history, tests, work logs, and review findings. Do **not** recreate the project from scratch. The previous `CHAINPILOT_MASTER_WORKFLOW.md`, `AGENTS.md`, and `docs/CODEX_WORK_LOG.md` are historical records, not active instructions. If they conflict with this document, this document controls the workflow; functional product requirements from the prior spec remain applicable unless explicitly superseded here. Do not delete historical files without user permission. Update root `CLAUDE.md` to point here.

**At the first session:** inspect `git status`, `git log -5 --oneline`, `docs/PROJECT_STATUS.md`, `docs/REVIEW_QUEUE.md`, and source/tests. Identify whether P0-T1 was approved and whether P0-T2 is already in progress. Do not assume either status. Resolve pending review findings first. If a task is incomplete, continue it; do not reset its status.

## 1. Product vision
Build **ChainPilot AI**, an end-to-end, AWS-deployable supply-chain control tower for retail operations. Users can explore demand forecasts, stockout risks, supplier/delivery risks, reorder recommendations, agent-generated explanations, and approval workflows. This is a realistic portfolio demonstration, **not** a claim of access to a real company's supply chain. Show synthetic data labels clearly.

### Core business flow
1. Ingest and validate historical sales, calendar/pricing data, delivery records, and simulated warehouse/supplier records.
2. Train and evaluate forecasting and delay-risk models using time-based splits and reproducible runs.
3. Generate forecast outputs, uncertainty bands, and delivery risk scores.
4. Combine these with current inventory and supplier lead times in deterministic inventory optimization.
5. Surface risk alerts and proposed actions on the dashboard.
6. Let LangGraph/Bedrock AI agents investigate with read-only tools and cite data/policy evidence.
7. Require manager approval before simulated purchase orders, transfers, or other state changes.
8. Execute approved **simulated** actions via authorized, idempotent APIs; write audit events and track results.

## 2. Technology choices and exclusions
- Backend: Python 3.11+ (choose and pin one supported version), FastAPI, Pydantic, SQLAlchemy, Alembic.
- Data: PostgreSQL, local CSV/Parquet, S3 for data/artifacts; pgvector for a small policy-document RAG index.
- ML: pandas, scikit-learn, LightGBM or XGBoost, joblib; optional MLflow if it adds demonstrable value.
- Agent layer: LangGraph, Amazon Bedrock; Pydantic structured outputs and narrowly scoped tools.
- Frontend: React/Next.js with TypeScript, charts, simple responsive UI.
- Async: SQS with a Python worker in AWS; a lightweight local worker for development. Avoid unnecessary queue infrastructure in P0.
- Local: Docker Compose; cloud: ECR, ECS Fargate, RDS PostgreSQL, S3, CloudFront, ALB, CloudWatch, IAM, Secrets Manager, Terraform, GitHub Actions.
- **Forbidden:** Kafka, Kubernetes, EKS, Helm, microservices without a clear reason, unnecessary frameworks and decorative complexity.
- Redis is optional and must be justified; it is not required for MVP.

## 3. Datasets and integrity
- **M5 forecasting:** https://www.kaggle.com/competitions/m5-forecasting-accuracy/data ; start with `sales_train_validation.csv`, `calendar.csv`, `sell_prices.csv`.
- **Olist e-commerce:** https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce ; orders, order items, products, sellers, customers as needed.
- **Synthetic operations:** deterministic seed generator for 3–5 warehouses, 100–500 products, suppliers, inventory, POs, lead times, shipping events, and costs.
- M5 and Olist describe different businesses. **Never join their IDs as though they refer to the same company.** Evaluate each ML model independently, then connect outputs to a clearly labeled simulated demo scenario.
- Dataset acquisition may require Kaggle login/acceptance; Claude must never invent downloaded data. If data unavailable, implement schema, generator, small test fixtures, and a clear manual download guide, then mark real-data training blocked.
- Keep raw data, trained model files, credentials and `.env` out of Git. Store only tiny safe fixtures and metadata. Respect dataset usage terms.
- Prevent leakage: chronological validation, lag/rolling features computed from available past observations, no actual-delivery fields in dispatch-time prediction.

## 4. Functional requirements and acceptance criteria
### A. Identity and authorization
- Roles: analyst (read), manager (approve), admin (manage).
- Authenticated APIs, server-side RBAC, no unauthorized approvals or writes, audit actor/timestamp.
### B. Dashboard
- Overview KPIs, forecast explorer, stockout risk list, supplier/shipment risk, AI investigation view, approval queue, audit timeline.
- Real backend API integration, loading/error/empty states, accessible labels, simulated-data badge.
### C. Forecasting
- Seasonal naive baseline and a tree-based model; 7/14/28-day product/location forecasts.
- Rolling-origin backtests; MAE, WAPE, bias, RMSSE, and suitable uncertainty evaluation. Record split dates, versions and metrics; no invented performance numbers.
### D. Delivery risk
- Logistic regression baseline and tree model, time-based split, PR-AUC, recall, precision, calibration.
- Explicitly distinguish historical Olist experiment from synthetic supplier risk in demo.
### E. Inventory decisions
- Define inventory position semantics, reorder points, safety stock, lead-time variability, MOQ, capacity, and cost constraints.
- Use deterministic, testable math; report units and assumptions; replay simulator vs simple reorder baseline.
### F. Agentic investigation
- LangGraph supervisor with demand/inventory/supplier/decision responsibilities; typed read-only tools, structured outputs, citations to records and policies, retry/timeout limits.
- No LLM-generated inventory math, invented evidence, or autonomous purchases.
### G. Approval workflow
- Proposal → pending → approved/rejected → executed/failed; role checks, transaction and concurrency safeguards, idempotency keys, audit trail.
- Only simulated execution in portfolio version; external supplier integrations require separate approval.
### H. Operations
- Health/readiness endpoints, migrations, Docker local startup, GitHub Actions tests, structured logs, deployment docs, basic security checks, backup/recovery instructions.

## 5. Suggested API surface
`GET /health`, `GET /ready`, `GET /dashboard/kpis`, `GET /forecasts`, `POST /forecasts/jobs`, `GET /jobs/{id}`, `GET /inventory/risks`, `POST /inventory/recommendations`, `GET /suppliers/risks`, `POST /agents/investigate`, `GET /agents/runs/{id}`, `POST /approvals/{id}/decision`, `GET /audit-events`. Use consistent validation/errors, pagination where needed, and OpenAPI docs. Adapt names to existing code rather than breaking working routes without reason.

## 6. Data model
Tables/entities: users, products, warehouses, inventory, inventory_movements, suppliers, purchase_orders, shipments, sales_daily, forecasts, forecast_runs, risk_alerts, recommendations, approvals, agent_runs, audit_events, and document_chunks. Define primary/foreign keys, indexes, uniqueness, timestamps, migration history, and transactional boundaries. Never silently overwrite stock; reconcile through movement records.

## 7. Recommended repository layout (grow incrementally)
```text
chainpilot-ai/
├── CLAUDE.md
├── CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md
├── docs/
│   ├── PROJECT_STATUS.md
│   ├── CLAUDE_WORK_LOG.md
│   ├── REVIEW_QUEUE.md
│   ├── DECISIONS.md
│   └── DATASETS.md
├── apps/
│   ├── api/               # FastAPI
│   └── web/               # React / Next.js
├── ml/
│   ├── demand_forecasting/
│   ├── delivery_risk/
│   └── inventory_optimization/
├── agents/                # LangGraph workflows and tools
├── workers/               # asynchronous tasks
├── data/
│   ├── raw/               # ignored
│   ├── processed/         # ignored
│   ├── synthetic/         # generated, ignored
│   └── sample/            # small committed fixtures
├── database/migrations/
├── infrastructure/terraform/
├── tests/
├── .github/workflows/
├── docker-compose.yml
├── .env.example
└── README.md
```
Keep existing working layout when sensible. Do not move files solely to match this tree.

## 8. Development roadmap and gates
Task IDs are guidance; **honor any already existing IDs** in `docs/PROJECT_STATUS.md` and do not rename completed tasks.

| Phase | Build | Completion gate |
|---|---|---|
| P0 Foundation | FastAPI/Postgres, Compose, configuration, CI, docs | API healthy; tests/lint/build pass; secure localhost defaults |
| P1 Core data | migrations, auth/RBAC, products, warehouses, inventory, seeds | CRUD and role tests pass; audit foundation |
| P2 Demand ML | M5 loader, EDA, baselines, features, backtesting, model artifacts | reproducible time-split metrics; inference API |
| P3 Delivery ML | Olist loader, baseline, risk model, evaluation | no leakage; evaluated and calibrated scores |
| P4 Inventory | stockout detection, reorder/transfer recommendations, simulator | deterministic tests and baseline comparison |
| P5 AI copilot | policy RAG, LangGraph tools, investigation traces | grounded output; tool and safety evaluation |
| P6 Frontend | dashboards and workflows integrated with API | browser e2e flows, errors/empty states |
| P7 Approval/security | human approval, audit, concurrency, idempotency | unauthorized and unapproved actions blocked |
| P8 AWS | Terraform, ECR/ECS/RDS/S3/ALB, CI/CD, observability | approved staging deployment, smoke tests, rollback |
| P9 Final polish | load/security tests, demo data, README, architecture, walkthrough | all acceptance checks documented; portfolio demo |

**Data timing:** no external dataset required for P0; generate small synthetic records in P1; acquire M5 in P2; acquire Olist in P3; use evaluated model outputs + simulated operations thereafter. Ask user for downloads when needed, not prematurely.

## 9. Claude-only development + self-review protocol
Claude is the **sole coding agent** and also performs an explicit second-pass self-review. Self-review is not an independent external review; label it honestly. Do not ask for Codex handoff, switch roles, or wait for Codex. The user approves milestones and risky operations.

For each task:
1. **Inspect:** `git status --short`, `git log -5 --oneline`, current status, prior issues, relevant code/tests. Preserve uncommitted user work.
2. **Plan:** identify exact scope, affected files, acceptance criteria and tests. Explain the plan briefly before changes.
3. **Implement:** small, understandable vertical slice; no unrelated refactors. Add meaningful tests.
4. **Verify:** execute available unit/integration tests, lint/format, Docker checks as relevant. Record commands, actual output summary, environment limits; never claim unrun tests passed.
5. **Self-review:** inspect `git diff`, check correctness, edge cases, security, readability, data leakage, secrets, failure handling, and consistency with the spec. Fix issues and re-run affected tests. Log remaining findings in `docs/REVIEW_QUEUE.md`.
6. **Document:** append an entry to `docs/CLAUDE_WORK_LOG.md`; update `docs/PROJECT_STATUS.md` and `docs/DECISIONS.md` for meaningful choices.
7. **Commit/handoff:** commit only if user has authorized commits, use descriptive messages, include commit SHA; otherwise state that changes are uncommitted. Set `READY_FOR_USER_CHECK` or `BLOCKED` and stop at the agreed checkpoint. Continue to next task only after user authorization, unless user explicitly requests a bounded batch.

### Allowed task statuses
`NOT_STARTED`, `IN_PROGRESS`, `SELF_REVIEW`, `CHANGES_REQUIRED`, `READY_FOR_USER_CHECK`, `APPROVED`, `BLOCKED`. Legacy `READY_FOR_REVIEW` / `CHANGES_REQUESTED` should be mapped carefully with an explanatory status note, **not** silently treated as approved.

### Project status template
```md
Current phase: P0
Current task: P0-T2
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: IN_PROGRESS
Branch: <actual branch>
Last commit: <actual SHA or none>
Acceptance criteria:
- [ ] ...
Tests executed: <commands and results>
Open findings: <IDs>
Next action: <one concrete step>
Blockers: <none or details>
```

### Work log template (append-only)
```md
## YYYY-MM-DD HH:MM timezone — TASK-ID
- Starting commit / branch:
- Objective and plan:
- Files changed and why:
- Tests run / actual results:
- Self-review findings and fixes:
- Known limitations / blockers:
- Ending commit (if any):
- Next recommended task:
```

### Review queue template
```md
## TASK-ID-R1 — [HIGH/MEDIUM/LOW] Short issue title
- Source: Claude self-review / test / user feedback
- File and reproduction:
- Expected behavior:
- Fix and regression test:
- Status: OPEN / FIXED / VERIFIED
```

## 10. Student-written, explainable code standard
- Write code an MSc AI/ML student can explain in an interview. Use straightforward functions, descriptive names, small modules, and conventional Python/TypeScript.
- Prefer a simple service/repository split where useful; no elaborate factory hierarchies, needless design patterns, hidden magic, or premature microservices.
- Add type hints, docstrings for non-obvious public functions, comments for **why** a decision exists, and examples for tricky formulas. Do not comment every obvious line.
- Make assumptions explicit, especially for forecasts, replenishment math, and synthetic data.
- Use realistic error handling, explicit return types, configuration via environment variables, and tests for edge cases.
- Do not deliberately introduce mistakes to make code appear human. Never fabricate benchmarks, metrics, security checks, deployments, or tests.
- README should explain what each major component does, how to run it, and tradeoffs a student can defend.

## 11. Git and file safety
- Work in the user's existing branch; inspect before changing. Never force push, delete user changes, rewrite history, or silently overwrite existing logs.
- Do not stage `.env`, secrets, credentials, raw Kaggle datasets, generated large models, or local caches.
- Keep legacy `AGENTS.md` / Codex log only as historical artifacts; optionally archive after user approval. Remove any *active* instruction requiring Codex review from current task state.
- Keep work log append-only; changes to status and issue queue must be traceable to a commit.
- If multiple tools might edit the repo, do not work concurrently in the same working tree.

## 12. AWS and cost/security guardrails
- **No AWS provisioning or paid Bedrock inference without explicit user approval** and a cost estimate. Set billing budgets and alerts first.
- Prefer local development; staging AWS first, production-like hardening later. Do not promise free deployment.
- Secure defaults: localhost-only dev published ports, safe SQLAlchemy URL construction for reserved-character passwords, non-root containers, no public database, least-privilege IAM, Secrets Manager, HTTPS, log redaction, backups, restricted CORS.
- GitHub Actions OIDC for AWS access; avoid static AWS keys. Terraform `plan` reviewed before `apply`.
- Deployment is complete only with real endpoint checks and documented infrastructure. If user does not approve cloud spending, mark deployment blocked and supply reproducible scripts, not a false 'deployed' claim.

## 13. Verification checklist per milestone
- Unit tests; PostgreSQL integration tests for database changes; UI tests for frontend changes.
- Ruff lint/format (and TypeScript lint/typecheck where applicable).
- `docker compose config`, build/start/health checks for relevant changes.
- Auth/RBAC and approval safety tests for write endpoints.
- Model split/leakage checks and metrics from actual runs for ML.
- No Kafka/Kubernetes; no committed secrets; docs match behavior.
- `git diff --check`, actual Git status/commit recorded.
- Any unavailable tool/test listed as **NOT VERIFIED**, not passed.

## 14. Definition of done for entire project
A reproducible local stack, documented data preparation, evaluated ML models, deterministic inventory engine, evidence-grounded agent workflow, working dashboard, secure simulated approvals, CI, tests, Terraform-based AWS deployment (only if authorized), observability, and a complete student-friendly README/demo. Each feature must be exercised, not just scaffolded. Keep an honest list of limitations.

## 15. First action after installing this document
1. Inspect the current repository and legacy handoff records.
2. Confirm P0-T1's latest actual status; if prior review findings remain unresolved, fix/verify them before proceeding.
3. If P0-T1 is complete, identify whether P0-T2 GitHub Actions CI has started. Continue that task as Claude developer with self-review and user checkpoint.
4. Update `docs/PROJECT_STATUS.md` to reflect the **Claude-only** protocol while preserving prior review history.
5. Do not start from zero or change unrelated code.
