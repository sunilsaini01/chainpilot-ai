# Acceptance checklist

Every requirement of the specification ([CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](../CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md)), with its status and the evidence. Written 2026-10-19 (P9-T4). This is a **self-assessment by the developer**, not an independent audit. Every "Met" points to something that can be rerun.

**Status:** ✅ met · 🟡 partly · ❌ not met · 🔁 changed by an owner-approved decision.
**Evidence:** test files are in `apps/api/tests/`, `ml/tests/`, `apps/web/src/**/*.test.ts(x)` and `apps/web/e2e/`; result files are in [results/](results/); D-xxx are in [DECISIONS.md](DECISIONS.md). CI = [ci.yml](../.github/workflows/ci.yml), green on every push (latest checked: run #45 on 6a4eeb2).

**Summary:** the definition of done (§14) is met. Not built: background jobs (SQS worker), three tables (`shipments`, `sales_daily`, `risk_alerts`), a separate EDA notebook and cost constraints. Changed by decision: Groq instead of Bedrock, PostgreSQL full-text search instead of pgvector, and LightGBM's text model files instead of joblib.

## §1 Core business flow

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Ingest and validate sales, calendar/prices, delivery records, simulated warehouse/supplier data | ✅ | `ml/demand_forecasting/m5_data.py`, `ml/delivery_risk/olist_data.py` (validation, `test_m5_data.py`, `test_olist_data.py`); seed `apps/api/app/seed.py` (`test_seed.py`); imports check every row (`test_forecasts.py`, `test_delivery_risk.py`) |
| 2 | Train and evaluate with time-based splits, reproducibly | ✅ | Rolling-origin backtests and a chronological Olist split; seeds and run keys recorded; [MODEL_RESULTS.md](MODEL_RESULTS.md) |
| 3 | Forecasts, uncertainty bands, delivery risk scores | ✅ | 853,720 forecast rows with 80% bands; 32,422 scored orders; both imported on staging |
| 4 | Combine with inventory and lead times in deterministic optimization | ✅ | `apps/api/app/inventory_policy.py`, `replenishment_service.py` (`test_inventory_policy.py`, `test_replenishment.py`) |
| 5 | Risk alerts and proposed actions on the dashboard | ✅ | Stock risks, Approval queue and Delivery risk screens (`screens.test.tsx`, `e2e/approvals.spec.ts`) |
| 6 | AI agents investigate with read-only tools and cite evidence | ✅ 🔁 | LangGraph with Groq instead of Bedrock (D-052); `test_copilot_graph.py`, `test_copilot_tools.py`, evaluation in [MODEL_RESULTS.md](MODEL_RESULTS.md#ai-copilot-first-real-evaluation-p5-t4) |
| 7 | Manager approval before any simulated order or transfer | ✅ | `test_approvals.py`, `test_security_sweep.py` |
| 8 | Approved actions executed through authorized, idempotent APIs, audited, tracked | ✅ | `approval_service.py`; idempotency and concurrency tests in `test_approvals.py`; outcome executed/failed stored |

## §2 Technology

| Requirement | Status | Evidence |
|---|---|---|
| Python 3.11 pinned; FastAPI, Pydantic, SQLAlchemy, Alembic | ✅ | `apps/api/Dockerfile` (`python:3.11-slim`), `requirements.txt` exact pins, migrations 0001–0012 |
| PostgreSQL; local CSV/Parquet | ✅ | Compose `postgres:16`; the ML code reads the M5 and Olist CSVs and writes CSV (Parquet is not used) |
| S3 for data and artifacts | 🟡 | S3 holds the dashboard and the staging import files; model artifacts stay local (`ml/artifacts/`, ignored by Git) |
| pgvector for the policy RAG index | 🔁 | PostgreSQL full-text search instead (D-048): six short policies did not need embeddings. Retrieval checked in [results/p5_policy_retrieval.json](results/p5_policy_retrieval.json) |
| pandas, scikit-learn, LightGBM, joblib; MLflow optional | ✅ 🔁 | Pinned in `ml/requirements.txt`. Models are saved in LightGBM's text format, not joblib or pickle, so loading cannot run code (`lgbm_model.save_models`). MLflow not used |
| LangGraph, Bedrock, Pydantic structured outputs, narrow tools | ✅ 🔁 | LangGraph and structured JSON outputs; Groq/Gemini instead of Bedrock (D-052, owner's choice for cost) |
| React/Next.js, TypeScript, charts, responsive UI | ✅ | React 19 + TypeScript + Vite; SVG forecast chart; the layout wraps on small screens |
| SQS with a worker in AWS, a local worker | ❌ | Not built. Forecasts and scores are produced offline and imported (D-039); `POST /forecasts/jobs` and `GET /jobs/{id}` do not exist |
| Docker Compose; ECR, ECS Fargate, RDS, S3, CloudFront, ALB, CloudWatch, IAM, Secrets Manager, Terraform, GitHub Actions | ✅ | `docker-compose.yml`; `infrastructure/terraform/`; deploy workflow; [AWS_RUNBOOK.md](AWS_RUNBOOK.md) |
| No Kafka, Kubernetes, EKS, Helm, needless microservices; Redis only if justified | ✅ | None used; rate limits and search also in PostgreSQL |

## §3 Datasets and integrity

| Requirement | Status | Evidence |
|---|---|---|
| M5 (sales_train_validation, calendar, sell_prices) | ✅ | [DATASETS.md](DATASETS.md); `m5_data.py` |
| Olist (orders, items, products, sellers, customers) | ✅ | [DATASETS.md](DATASETS.md); `olist_data.py` |
| Deterministic synthetic operations: 3–5 warehouses, 100–500 products, suppliers, inventory, POs, lead times, shipping events, costs | 🟡 | Seed 42: 4 warehouses, 200 products, 6 suppliers, 210 POs with lead times and unit costs (`test_seed.py`). **No shipping events** (no `shipments` table) |
| Never join M5 and Olist IDs as one company; evaluate separately | ✅ | Separate pipelines and screens; the M5 demand is a labelled "borrowed" demo link (D-044); Olist labelled on every response (`X-Dataset`) |
| No invented data | ✅ | Real downloads by the owner; synthetic fixtures and test forecasts are labelled SYNTHETIC |
| Raw data, models, credentials, `.env` out of Git | ✅ | `.gitignore`; `.env.example` only |
| No leakage: chronological validation, past-only features, no actual-delivery fields at dispatch | ✅ | `test_lgbm_model.py` (training rows never pass the origin; predictions unchanged when future sales change); `test_publish.py` (future rows carry no sales); `test_olist_data.py` (no forbidden column is a feature; features unchanged when the delivery date changes; split by purchase date) |

## §4 Functional requirements

| Area | Requirement | Status | Evidence |
|---|---|---|---|
| A | Roles analyst / manager / admin; authenticated APIs; server-side RBAC; no unauthorized writes; audit actor and time | ✅ | `test_security_sweep.py` (all 43 operations: no login, the role below, missing CSRF); `test_auth_api.py`; `audit_events` |
| B | Overview, forecast explorer, stock-out risks, supplier/shipment risk, AI investigation, approval queue, audit timeline | ✅ | Every screen in `apps/web/src/pages/`; browser tests `e2e/*.spec.ts` |
| B | Real API, loading/error/empty states, accessible labels, simulated-data badge | ✅ | `e2e/states.spec.ts`; axe WCAG 2.1 A/AA on every page (`e2e/accessibility.spec.ts`); manual screen-reader check still open (P6-T4-R3) |
| C | Seasonal naive baseline and a tree model; 7/14/28-day forecasts | ✅ | [MODEL_RESULTS.md](MODEL_RESULTS.md) (baselines, LightGBM, weekly LightGBM) |
| C | Rolling-origin backtests; MAE, WAPE, bias, RMSSE, uncertainty; split dates and versions recorded; no invented numbers | ✅ | [results/](results/) (`p2_baselines.json`, `p2_lightgbm.json`, `p2_model_selection.json`); unseen 28-day check [p2_holdout.json](results/p2_holdout.json) |
| D | Logistic regression and a tree model, time-based split, PR-AUC, recall, precision, calibration | ✅ | [p3_delivery_risk.json](results/p3_delivery_risk.json), [p3_delivery_risk_rolling.json](results/p3_delivery_risk_rolling.json), [tiers](results/p3_delivery_risk_tiers.json) |
| D | Olist experiment kept apart from the synthetic supplier risk | ✅ | Separate screen and labels; the supplier ratings come from the simulated orders (`purchasing_service.py`) |
| E | Inventory position, reorder points, safety stock, lead-time variability, MOQ, capacity | ✅ | `inventory_policy.py` with worked examples in tests; capacity in `inventory_service.py` (`test_capacity_and_paging.py`) |
| E | Cost constraints | 🟡 | Unit costs are stored and priced into orders and stock value, but there is no ordering or transfer cost and no budget, so the plan does not trade a transfer against an order (P4-T4-R3) |
| E | Deterministic, testable math; units and assumptions; replay vs a simple reorder baseline | ✅ | [p4_inventory_replay.json](results/p4_inventory_replay.json): 17–34% less stock for the same fill rate |
| F | LangGraph supervisor with demand/inventory/supplier/decision roles; typed read-only tools; structured output; citations; retry and timeout limits | ✅ | `app/copilot/graph.py`, `tools.py`; call, tool and round limits; read-only transactions with a 5 s timeout |
| F | No LLM inventory math, no invented evidence, no autonomous purchases | ✅ | Numbers come from tools only; citations are checked and removed if a tool did not return them; the copilot has no write tool (`test_copilot_tools.py`, the evaluation's database-change check) |
| G | pending → approved/rejected → executed/failed; roles, transactions, concurrency, idempotency, audit | ✅ | `test_approvals.py` (including two managers at once with threads), mutation-checked |
| G | Simulated execution only | ✅ | Orders and transfers stay inside the database; no external integration |
| H | Health and readiness, migrations, Docker startup, CI tests, structured logs, deployment docs, security checks, backup and recovery | ✅ | `test_health.py`, `test_migrations.py`, `test_logging.py` (JSON logs); CI; [AWS_RUNBOOK.md](AWS_RUNBOOK.md) with backup and recovery (restore tested 2026-10-19: all 20 tables identical) |

## §5 API surface

| Suggested | Actual | Status |
|---|---|---|
| `GET /health`, `GET /ready`, `GET /dashboard/kpis`, `GET /forecasts`, `GET /inventory/risks`, `POST /inventory/recommendations`, `GET /suppliers/risks`, `POST /agents/investigate`, `GET /agents/runs/{id}`, `GET /audit-events` | Same paths | ✅ |
| `POST /approvals/{id}/decision` | `POST /inventory/recommendations/{id}/decision` plus `GET /approvals` (D-059: next to the existing recommendation routes) | ✅ |
| `POST /forecasts/jobs`, `GET /jobs/{id}` | Not built (no worker) | ❌ |
| Consistent validation and errors, paging, OpenAPI docs | `X-Total-Count` paging, Pydantic validation, `/docs` | ✅ |

## §6 Data model

| Requirement | Status | Evidence |
|---|---|---|
| users, products, warehouses, inventory, inventory_movements, suppliers, purchase_orders, forecasts, forecast_runs, recommendations, approvals, agent_runs, audit_events, document_chunks | ✅ | `app/models.py`, migrations 0001–0012 (`test_models_and_migrations_are_in_sync`, up/down round trip) |
| shipments, sales_daily, risk_alerts | ❌ | Not created. Delivery risk is stored as `delivery_risk_scores` (with tiers); stock-out risks are calculated on request; M5 sales stay in the ML pipeline |
| Keys, indexes, uniqueness, timestamps, transactions; stock never overwritten, only through movements | ✅ | `record_movement` ledger with row locks (`test_inventory_service.py`), `updated_at` triggers |

## §8 Phase gates

| Phase | Gate | Status |
|---|---|---|
| P0 | API healthy; tests, lint and build pass; secure localhost defaults | ✅ |
| P1 | CRUD and role tests; audit foundation | ✅ |
| P2 | Reproducible time-split metrics; inference API | ✅ (`GET /forecasts` serves the imported forecasts) |
| P3 | No leakage; evaluated and calibrated scores | ✅ |
| P4 | Deterministic tests and baseline comparison | ✅ |
| P5 | Grounded output; tool and safety evaluation | ✅ (run 1 passed the gate, run 2 did not: both reported, P5-T4-R6/R7 left open by the owner) |
| P6 | Browser e2e flows, error and empty states | ✅ |
| P7 | Unauthorized and unapproved actions blocked | ✅ |
| P8 | Approved staging deployment, smoke tests, rollback | ✅ (rollback tested automatically and by hand) |
| P9 | Load and security tests, demo data, README, architecture, walkthrough | ✅ load and security, demo, README, architecture; 🟡 manual walkthrough (P9-T5) |

## §10–§13 Code, Git, AWS and verification rules

| Requirement | Status | Evidence |
|---|---|---|
| Explainable, student-level code; type hints; comments explain why; no fabricated results | ✅ | Self-assessed; mistakes and failed runs are recorded in [CLAUDE_WORK_LOG.md](CLAUDE_WORK_LOG.md) |
| README explains components, how to run, trade-offs | ✅ | [README.md](../README.md) |
| No force pushes or history rewrites; no secrets staged; append-only work log | ✅ | The owner commits and pushes; corrections are appended, not edited |
| No AWS spending without approval and an estimate; budgets first | ✅ | [AWS_PLAN.md](AWS_PLAN.md), D-063; budget created before staging |
| Localhost-only ports, safe DB URL, non-root containers, no public DB, least-privilege IAM, Secrets Manager, HTTPS, log redaction, backups, restricted CORS | ✅ 🟡 | All in place; IAM is **scoped but not minimal** (service wildcards for Terraform, P8-T1-R2 notes); CloudFront to the internal load balancer is HTTP inside the VPC |
| OIDC for GitHub; plan reviewed before apply; real endpoint checks | ✅ | Deploy workflow with approval; `smoke-test.py` |
| Verification per milestone; unavailable checks marked NOT VERIFIED | ✅ | Work log entries |

## §14 Definition of done

| Item | Status |
|---|---|
| Reproducible local stack | ✅ `docker compose up` + `scripts/demo-setup.sh` (tested from scratch and repeated) |
| Documented data preparation | ✅ [DATASETS.md](DATASETS.md) |
| Evaluated ML models | ✅ [MODEL_RESULTS.md](MODEL_RESULTS.md) |
| Deterministic inventory engine | ✅ |
| Evidence-grounded agent workflow | ✅ (with documented limits) |
| Working dashboard | ✅ local and on AWS |
| Secure simulated approvals | ✅ |
| CI and tests | ✅ 715 tests; 6 CI jobs |
| Terraform-based AWS deployment (authorized) | ✅ staging, demo days only |
| Observability | ✅ JSON logs, CloudWatch alarms (email tested) and dashboard |
| Student-friendly README and demo | ✅ [README.md](../README.md), [DEMO.md](DEMO.md) |
| Honest list of limitations | ✅ README "Limitations"; [REVIEW_QUEUE.md](REVIEW_QUEUE.md) |
