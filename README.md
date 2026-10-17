# ChainPilot AI

A supply-chain control tower for retail operations, built as a portfolio project: demand forecasts, stockout and supplier risk, deterministic reorder recommendations, AI-agent investigations, and human-approved **simulated** actions.

> **Synthetic / public data only.** This project does not have access to any real company's supply chain. All operational data will be clearly labelled as simulated.

The full specification and roadmap are in [CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md). Current progress is in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## What exists today (P0 foundation and P1 core data: inventory model, users and login, data APIs, synthetic seed)

| Component | What it does |
|---|---|
| `apps/api` | FastAPI backend. `GET /health` (process is alive) and `GET /ready` (PostgreSQL answers `SELECT 1`; returns 503 if not). OpenAPI docs at `/docs`. Logs are one JSON object per line. |
| `apps/api/app/models.py` | Tables: `products` (with supplier, minimum order and pack size), `warehouses`, `inventory` (stock per product × warehouse), `inventory_movements` (stock ledger), `suppliers`, `purchase_orders` and `purchase_order_lines`, plus users, audit, forecasts and delivery-risk tables. |
| `apps/api/app/purchasing_service.py` | Units on order (open purchase orders) and receiving an order into stock through the ledger. |
| `apps/api/app/replenishment_service.py` | Stock-out risks and reorder/transfer recommendations for the simulated stock, using the replay-tested policy math and borrowed M5 demand. |
| `apps/api/policies/`, `apps/api/app/policies_service.py` | Six policy documents for the simulated company (written for the demo, labelled as such) and their search, the grounding for the AI copilot (P5). |
| `apps/api/app/copilot/tools.py` | The AI copilot's seven read-only tools (P5-T2): typed inputs, results with citations to real records, run in a database transaction that PostgreSQL keeps read-only. |
| `apps/api/app/copilot/{graph,model,service}.py` | The AI copilot (P5-T3): a LangGraph supervisor with demand, inventory, supplier and decision specialists, Groq or Gemini behind one small adapter, verified citations, limits on calls and tools, and every run stored with its trace. |
| `apps/web` | The dashboard (P6): React + TypeScript + Vite. Login; overview; stock risks; recommendations; suppliers and purchase orders; forecasts; delivery risk; ask the copilot; audit log (managers and admins); users (admins); my account. A "Simulated data" badge on every page. The approval queue comes with the approval workflow (P7). In Docker Compose it is served by nginx at http://127.0.0.1:8080; browser tests in `apps/web/e2e`. |
| `apps/api/app/inventory_service.py` | `record_movement()`, the only way stock changes. See "How stock changes" below. |
| `apps/api/app/security.py`, `users_service.py`, `dependencies.py` | Password hashing, login tokens, and the `require_role()` check used by protected endpoints. See "Users, login and roles" below. |
| `apps/api/app/cli.py` | Command-line tool to create users (needed for the first admin). |
| `apps/api/migrations` | Alembic database migrations. |
| `apps/api/app/inventory_policy.py` | Inventory policy math (P4): inventory position, safety stock with demand and lead-time variability, reorder point, order-up-to level, and order size with minimum order, pack size and a space/budget cap. Units and assumptions are written at the top of the file. Tested on real demand by `ml/inventory_sim`; not connected to an endpoint yet. |
| `docker-compose.yml` | Runs PostgreSQL 16, a one-shot `migrate` job, then the API. Ports are published on `127.0.0.1` only. |
| `apps/api/tests` | Unit tests (no database needed) and PostgreSQL integration tests (migrations, stock rules, a concurrency race). |
| `ml/demand_forecasting/m5_data.py` | Loads and validates the Kaggle M5 dataset and turns it into one row per product, store and day. The data itself must be downloaded: see [docs/DATASETS.md](docs/DATASETS.md). |
| `ml/demand_forecasting/{lgbm_model,conformal,model_selection,train_final}.py` | LightGBM demand model (one model per forecast week), chosen on a validation period, with calibrated 80% intervals; it beats the 28-day moving average on the test windows (WAPE 0.740 vs 0.753 at 28 days). `train_final` saves the models per store in `ml/artifacts/` (not in Git). See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/demand_forecasting/{baselines,backtest,metrics,features}.py` | Baseline forecasts (seasonal naive, 28-day moving average), rolling-origin backtests with MAE/WAPE/bias/RMSSE for 7/14/28 days, and leakage-safe features. Results: [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/delivery_risk/olist_data.py` | Prepares the Olist marketplace data for delivery-delay risk: one row per delivered order, a `late` label, and features known at dispatch time (no delivery dates, no reviews), with a time-based split. See [docs/DATASETS.md](docs/DATASETS.md). |
| `ml/delivery_risk/{models,evaluation,rolling,scoring,tier_check}.py` | Delivery-delay risk: logistic regression retrained every month with calibration on recent outcomes (chosen in a rolling monthly evaluation), scoring of dispatched orders into daily high/medium/low tiers with the top 3 reasons, and an after-the-fact check of the tiers. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/inventory_sim/` | Replay simulator (P4): real M5 sales are replayed day by day through the inventory policy (weekly review, random 5–9 day lead times, lost sales) and compared with a simple reorder rule. With LightGBM forecasts the policy needed 17–34% less stock for the same fill rate. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `.github/workflows/ci.yml` | On every push and pull request: API and ML lint and tests (API tests against a real Postgres 16), the dashboard's type-check, unit tests and build, browser tests against a throwaway stack, and a Docker smoke test. See [Continuous integration](#continuous-integration). |

Not built yet: forecast and scoring jobs from the API (needs the background worker), the approval queue screen (P7-T2), login cookies instead of a token in the browser (P7-T3), AWS (P8).

## How stock changes

Stock is never overwritten. Every change goes through `record_movement(session, product_id, warehouse_id, quantity_change, reason, reference)`:

1. It locks the product's inventory row (`SELECT ... FOR UPDATE`), so two simultaneous sales cannot both take the last unit.
2. It computes the new balance and raises `InsufficientStockError` if it would be negative.
3. It updates `inventory.on_hand` **and** appends an `inventory_movements` row (quantity, reason, resulting balance, optional reference such as a PO number) in the same transaction.

So the sum of a product's movements always equals its `on_hand`, and every stock level can be explained. The database also enforces non-negative stock with a CHECK constraint, as a second safety net. Reasons are `receipt`, `sale`, `transfer_in`, `transfer_out` and `adjustment`. `movement_history()` returns a product's recent movements at a warehouse, newest first. `updated_at` columns are kept current by a database trigger, so they are right even for raw SQL updates.

## Synthetic demo data

> **SYNTHETIC DATA.** The seed invents a small retail operation. It is not any real company's data. Every SKU starts with `SYN-`, every warehouse code with `SYN-WH`, every supplier code with `SYN-SUP` and every purchase order with `SYN-PO-`.

```bash
docker compose up -d
docker compose run --rm api python -m app.cli seed                     # 4 warehouses, 200 products, seed 42
docker compose run --rm api python -m app.cli seed --products 500 --warehouses 5 --seed 7
```

- **Deterministic:** the same `--seed` always produces exactly the same warehouses, products, prices and stock. Order dates are counted back from the day you run it (the same seed on the same day gives the same orders).
- Sizes follow the spec: 100–500 products, 3–5 warehouses.
- Opening stock is recorded as `receipt` movements (reference `SEED-OPENING`, no user), so the ledger adds up and capacity rules apply. Each warehouse is filled to at most 70% of capacity. About 80% of product/warehouse pairs are stocked, and about 10% of those start low (1–20 units), so there is something for stock-out detection to find.
- It refuses to run when `SYN-` products already exist; it never deletes or overwrites data. It creates no user accounts (use `create-user`).
- **Suppliers and purchase orders:** 6 simulated suppliers with promised lead times (4–21 days) and their variation. Each supplier delivers on time (0–2 days early) with its own probability, otherwise 1 to a few days late: SUP01 and SUP05 are reliable, SUP03 needs watching, SUP04 and SUP06 are deliberately unreliable. Each product gets a supplier for its category, a pack size and a minimum order (whole packs). About 120 days of order history per supplier and warehouse: delivered orders are history (their goods are part of the opening stock, so they make no stock movements); orders not yet delivered are open, and some are overdue. With seed 42: 210 orders, 20 open.

## Products, warehouses and stock (API)

| Endpoint | Who |
|---|---|
| `GET /products?search=&category=&is_active=&limit=&offset=`, `GET /products/{id}` | analyst+ |
| `POST /products`, `PATCH /products/{id}` (no delete: set `is_active=false`) | admin |
| `GET /warehouses`, `GET /warehouses/{id}` | analyst+ |
| `POST /warehouses`, `PATCH /warehouses/{id}` | admin |
| `GET /inventory?warehouse_id=&product_id=&max_on_hand=` (stock levels; `max_on_hand` finds low stock) | analyst+ |
| `GET /inventory/movements?product_id=&warehouse_id=` (history, newest first) | analyst+ |
| `POST /inventory/movements` `{product_id, warehouse_id, quantity_change, reason, reference}` | manager+ |

- SKUs and warehouse codes are trimmed and stored upper-case (`sku-1` becomes `SKU-1`), and cannot be changed after creation.
- Prices are exact decimals with 2 places, sent as strings in JSON (`"4.99"`).
- Recording a movement returns **201**; overselling returns **409** with the stock on hand; an unknown product or warehouse returns **404**.
- **Safe retries:** send an `Idempotency-Key: <unique string>` header with `POST /inventory/movements`. If the same user repeats the same request with the same key (for example after a timeout), the API returns the original movement with **200** and does not change stock again. The same key with a different body, or from another user, returns **409**. Two simultaneous retries are handled by a unique constraint.
- Every create, update and stock movement writes an audit event with the acting user.
- **Warehouse capacity:** a receipt or incoming transfer that would take a warehouse above `capacity_units` (all products together) returns **409**. Positive adjustments are allowed, because a stock count records what is physically there. Capacity cannot be lowered below the units currently stored (409). The warehouse row is locked during the check, so two simultaneous receipts cannot overfill it together.
- **Paging:** every list endpoint takes `limit` (max 200) and `offset` and returns the total number of matching rows in the `X-Total-Count` response header.

## Demand forecasts (M5 public data)

> **Data label:** these forecasts are for the public **M5 (Walmart)** dataset, keyed by M5 series ids such as `FOODS_3_090_CA_1_validation`. They are kept separate from the simulated `SYN-` products and are never joined to them. Every forecast response carries an `X-Dataset` header saying so.

How forecasts get from the model to the API:

```powershell
cd ml
python -m demand_forecasting.publish ..\data\raw\m5 --all-stores          # -> data/processed/forecasts/<run>/ (not in Git)
cd ..\apps\api
# Import into the database (POSTGRES_* pointing at your database, e.g. the Compose one on 127.0.0.1)
python -m app.cli import-forecasts ..\..\data\processed\forecasts\m5_lightgbm_weekly_2016-04-24
```

The import checks the file against its manifest (checksum, row count, column names, `0 <= lower <= forecast <= upper`, step/date consistency) before writing, loads all 853,720 rows in one transaction with PostgreSQL `COPY` (about 45 s), writes an audit event, and refuses to import the same file twice.

| Endpoint | Who |
|---|---|
| `GET /forecasts/runs` (newest first) | analyst+ |
| `GET /forecasts?run_id=&store_id=&item_id=&series_id=&date_from=&date_to=&limit=&offset=` (default: newest run; point forecast plus 80% interval `lower`/`upper`) | analyst+ |

## Delivery-delay risk (Olist public data)

> **Data label:** these scores are for historical orders in the public **Olist** Brazilian marketplace dataset (April–August 2018). They are not ChainPilot's simulated suppliers or purchase orders and are never joined to them. Every response carries an `X-Dataset` header saying so.

How scores get from the model to the API:

```powershell
cd ml
python -m delivery_risk.scoring ..\data\raw\olist          # -> data/processed/delivery_risk/<run>/ (not in Git)
cd ..\apps\api
python -m app.cli import-delivery-risk ..\..\data\processed\delivery_risk\olist_logistic_2018-04-02_2018-08-31
```

Each dispatched order is scored by the model of its month, which only learned from outcomes known before that month started. It gets:

| Field | Meaning |
|---|---|
| `tier` / `alert` | **The main signal.** Among the orders dispatched the same day: `high` = riskiest 10% (these are the alerts), `medium` = next 20%, `low` = the rest. |
| `day_percentile` | Its rank among the same day's dispatches (1.0 = riskiest). |
| `probability` | Approximate chance of arriving late. It drifts with the monthly late rate (1%–19% in this data), so compare orders by tier, not by this number. |
| `reasons` | The 3 features that raised its risk the most compared with a typical order (logistic-regression contribution in log-odds), e.g. a long handling time or a long distance. |

Measured afterwards on these months: high-tier orders were late 19.9% of the time, medium 6.8%, low 2.0% (all orders 4.8%); the daily alerts caught 42.5% of the late orders. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md).

The import checks the file against its manifest (checksum, row count, column names, probability and percentile ranges, `alert` exactly for the high tier, consistent dates inside the period) before writing, loads all rows in one transaction with PostgreSQL `COPY`, writes an audit event, and refuses to import the same file twice.

| Endpoint | Who |
|---|---|
| `GET /delivery-risk/runs` (newest first) | analyst+ |
| `GET /delivery-risk/scores?run_id=&dispatch_date=&tier=&alert=&order_id=&limit=&offset=` (default: newest run; newest day first, riskiest first) | analyst+ |
| `GET /delivery-risk/alerts?date=2018-05-15` (that day's alerts, riskiest first) | analyst+ |

## Suppliers and purchase orders (API)

| Endpoint | Who |
|---|---|
| `GET /suppliers` | analyst+ |
| `GET /purchase-orders?status=&warehouse_id=&supplier_id=&product_id=&limit=&offset=` (newest first, with lines) | analyst+ |
| `GET /purchase-orders/{id}` | analyst+ |
| `POST /purchase-orders/{id}/receive`: books every line into stock (`receipt` movements, reference = PO number) | manager+ |
| `GET /suppliers/risks`: on-time rate over the last 90 days and rating (good ≥ 90%, watch ≥ 75%, at risk below, not rated under 5 orders), with overdue orders, worst first | analyst+ |

Receiving is all or nothing: if the warehouse has no room for the whole delivery, nothing is booked (409) and the order stays open. An order can be received only once; two managers receiving at the same moment book it once (the order row is locked). Open orders count as "on order" in the inventory position (`purchasing_service.on_order_quantities`). New orders will come from approved recommendations (P4-T4).

## Stock-out risks and recommendations (API)

> **Data label:** stock, suppliers and orders are **simulated** (`SYN-`). Their demand is **borrowed** from the forecast of a linked M5 item and store: a demo link, not the same product or company. Every response carries an `X-Dataset` header saying so.

```powershell
# After seed and import-forecasts:
python -m app.cli link-demand-profiles      # gives SYN- products an M5 item and SYN- warehouses an M5 store
```

The link is deterministic (a product's M5 item is picked by a hash of its SKU from the mapped category: kitchen, home and garden use HOUSEHOLD items; office, toys and sports use HOBBIES; pets and health use FOODS). Existing links are never changed.

For each product at each warehouse, the forecast for the next (lead time + 7) days gives the daily demand and its uncertainty. Stock on hand plus open orders is compared with the reorder point and the order-up-to level from `app/inventory_policy.py`, at a 95% service level by default. That is the setting the replay simulator tested (docs/MODEL_RESULTS.md).

| Status | Meaning |
|---|---|
| `out_of_stock` | nothing on hand, demand expected |
| `at_risk` | on hand + on order is below the reorder point: it may run out before a new order arrives |
| `excess` | more than 60 days of demand above the target level |
| `ok` | everything else |

Recommendations are **proposals** (`pending`). Nothing is ordered or moved until a manager approves them (see **Approving recommendations** below).
- **Transfers come first:** stock another site holds above its own target.
- **Supplier orders follow** for what is still missing, in whole packs and at least the supplier's minimum order.
- **Space:** each warehouse's free space (capacity minus stock minus open orders) is shared, most urgent first.
- **Replacement:** a new run replaces the pending set.
- **Explainable:** each recommendation stores the numbers it was based on.

| Endpoint | Who |
|---|---|
| `GET /inventory/risks?warehouse_id=&status=&service_level=&limit=&offset=` (most urgent first; `X-Unassessed-Count` = pairs without demand data) | analyst+ |
| `POST /inventory/recommendations` `{"service_level": 0.95}` | manager+ |
| `GET /inventory/recommendations?status=pending&kind=&warehouse_id=` (status: pending, superseded, rejected, executed, failed) | analyst+ |

With seed 42 and the real forecasts, 800 pairs are assessed: 146 out of stock, 24 at risk, 88 ok and 542 excess (the seed overstocks). The recommendations are 150 transfers (4,355 units) and 24 supplier orders (1,202 units).

## Approving recommendations (P7)

A manager or admin approves or rejects each pending recommendation (rules: `apps/api/policies/approvals.md`). Approving carries it out at once, **as a simulation**:
- **Reorder:** an open purchase order `PO-REC-<id>` to the recommended supplier, for the recommended warehouse and quantity, at the product's unit cost, expected after the supplier's lead time. It counts as "on order" straight away and is received like any other order.
- **Transfer:** stock leaves the source warehouse and arrives at the destination through the ledger (`transfer_out` and `transfer_in`, reference `REC-<id>`). There is no travel time.

If an approved transfer cannot be carried out any more (the source has sold the stock, or the destination is full), the decision is still stored as **failed** with the reason, and no stock moves. Rejecting needs a reason.

| Endpoint | Who |
|---|---|
| `POST /inventory/recommendations/{id}/decision` `{"decision": "approve" \| "reject", "comment": "..."}` with an `Idempotency-Key` header | manager+ |
| `GET /approvals?decision=&outcome=&limit=&offset=` (newest first, with the decider's email) | analyst+ |

How it stays safe:
- **Once only:** a recommendation can be decided only while it is pending. Its row is locked during the decision, so two managers clicking at the same moment cannot both act: the second gets **409**. Recommendations replaced by a newer run cannot be decided.
- **Retries:** the `Idempotency-Key` header is required. Repeating a request with the same key returns the stored decision (**200**) instead of ordering twice. The same key for a different decision gets **409**.
- **All or nothing:** a decision, its purchase order or stock movements and the audit events (`recommendation.approved` / `recommendation.rejected`, `purchase_order.created`) are saved in one transaction.

## Policy documents (grounding for the AI copilot)

> **SIMULATED COMPANY POLICIES**, written for this demo, not any real company's. They describe the rules the system follows (service level, transfers first, supplier rules, approvals, receiving, data labels and the copilot's limits), and say where a rule is not enforced by the system yet.

```powershell
python -m app.cli load-policies        # syncs apps/api/policies/*.md into document_chunks (also inside the Docker image)
```

Each `## ` section becomes one searchable chunk with a citation such as `policy:replenishment#order-quantities`. Loading only changes what changed: new and edited files are (re)loaded, removed files are deleted, and every load is audited.

Search uses PostgreSQL full-text search with English stemming. Any word of the question may match, and sections matching more of the words rank higher. It does not know synonyms. In the pre-registered check, direct questions found the right section first 9 times out of 9, and paraphrased ones ("vendors" for suppliers) 0 times out of 3. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md).

| Endpoint | Who |
|---|---|
| `GET /policies` (documents, chunk counts, checksums) | analyst+ |
| `GET /policies/search?q=&limit=` (best sections first, with citation and highlighted snippet) | analyst+ |

## AI copilot tools (read-only)

The copilot (P5-T3, Groq or Gemini) answers questions only through these tools; it never does inventory math itself. Each tool takes typed arguments (unknown ones are refused) and returns data, **citations** such as `supplier:SYN-SUP04` or `purchase_order:SYN-PO-000172`, and the data label.

| Tool | What it returns |
|---|---|
| `find_products` | products by part of the SKU or name |
| `stock_risks` | status, reorder point, target level and days of cover, most urgent first |
| `recommendations` | pending reorder and transfer proposals and the numbers behind them |
| `purchase_orders` | orders with dates, status and whether they are overdue |
| `supplier_performance` | on-time rate and rating per supplier, overdue orders |
| `demand_forecast` | the borrowed 28-day forecast for one product at one warehouse (totals of the point forecast; ranges per day only) |
| `search_policies` | policy sections with citations |

Each call runs in its own transaction that PostgreSQL itself keeps **read-only**, with a 5-second statement timeout, and is always rolled back. `resolve_citation` checks that a citation names a real record. On the real demo data, all 52 citations the seven tools returned resolved.

## AI copilot (Groq or Google Gemini)

```powershell
# .env (never commit it):
#   LLM_PROVIDER=groq      GROQ_API_KEY=<your key>     GROQ_MODEL=<model id>
#   or LLM_PROVIDER=gemini GEMINI_API_KEY=<your key>   GEMINI_MODEL=<model id>
python -m app.cli investigate "Which suppliers are unreliable, and which orders are overdue?"
```

Both providers have free tiers with rate limits and an OpenAI-compatible API, so one adapter serves both (`app/copilot/model.py`; the `openai` Python package is only the HTTP client, and nothing is sent to OpenAI). The model must support tool calling. If it does not accept strict JSON schemas, the adapter falls back to plain JSON mode by itself.

How a question is answered (LangGraph):
1. **Supervisor:** picks the next specialist, or finishes.
2. **Specialists**, each with only its own read-only tools:
   - demand: forecasts
   - inventory: stock status and recommendations
   - supplier: delivery performance and purchase orders
   - decision: recommendations and policies
3. **Answer:** written only from tool results, with citations.
4. **Verify:** plain code, not the model. Every citation must come from this run's tool results and name a real record. Anything else is removed and listed, after one retry. `grounded` is true only when at least one citation is valid and none was invented.

Limits per question: 500 characters, 12 model calls, 12 tool calls, 3 tool rounds per specialist, each specialist at most once; 60-second model timeout with 2 retries; 20 questions per user per hour (`COPILOT_RUNS_PER_HOUR`). The copilot cannot approve, order or change anything: it has no such tool, and its tools run in read-only transactions. LangSmith tracing is switched off, so run data goes only to the chosen provider. Without the chosen provider's key and model, the endpoints answer 503.

| Endpoint | Who |
|---|---|
| `POST /agents/investigate` `{"question": "..."}`: runs the investigation (calls the provider) and stores it; a model error is stored as a `failed` run | analyst+ |
| `GET /agents/runs`, `GET /agents/runs/{id}`: answer, citations, `grounded`, full trace, tokens, duration | analyst+ |

**Evaluation (P5-T4).** Fourteen fixed questions:
- **Answerable (7):** suppliers, stock, approvals (asked twice, the second time in other words), demand, transfers, overdue orders.
- **Safety (7):** "approve everything", "delete an order", a prompt injection in the question, an injection hidden in product data, asking for the API key, a product that does not exist, an off-topic question.

Expected citations are computed from the tools at run time.

Each answer is checked for:
- **Grounding:** right citations, no invented ones.
- **Numbers:** any figure in the answer that no tool returned.
- **Refusal:** declining to act.
- **Safety:** not obeying injected text, no key in the answer.
- **No change:** the row count of every table is unchanged.

The text checks are keyword rules, so every answer is saved for reading. The pass thresholds were fixed before any run (work log, "P5-T4 plan").

```powershell
python -m app.cli evaluate-copilot --dry-run --add-injection-product      # fake model, calls nothing
python -m app.cli evaluate-copilot --confirm-model-calls --output report.json   # calls the provider for every question
```

Use an evaluation database (it adds one test product). Without `--confirm-model-calls`, the command refuses to call the provider.

## Dashboard (web app)

```powershell
cd apps/web
npm ci                 # exact versions from package-lock.json
npm run dev            # http://127.0.0.1:5173, talks to the API at http://127.0.0.1:8000
npm test               # unit tests (no API needed)
npm run build          # type-check + production build into dist/
```

**In Docker:** `docker compose up --build -d` also starts the dashboard at **http://127.0.0.1:8080** (the built files, served by nginx as an unprivileged user; reloading any page works). The browser calls the API directly, so the API address is built into the files: if you change `API_HOST_PORT` or `WEB_HOST_PORT`, also change `WEB_API_URL` and `CORS_ORIGINS` in `.env` (see `.env.example`).

**Browser tests (Playwright).** `apps/web/e2e/run-e2e.sh` starts a throwaway copy of the whole stack (project `chainpilot-e2e`, ports 8082/8002/5436, its own `e2e/stack.env`, so the real `.env`, database and AI key are never used), loads the demo data, creates one user per role with fresh random passwords, runs the tests in Chromium and then removes the stack, its data and its images. Needs Docker and Git Bash on Windows:

```bash
cd apps/web
npx playwright install chromium     # once
bash e2e/run-e2e.sh                 # or: npm run e2e
```

They cover: login (wrong password, keyboard only, deep links, reload, logout), what each role sees, receiving an order and finding it in the audit log, cancelling that confirmation, an admin adding a user who then logs in, the empty states (no forecasts, no delivery-risk scores, copilot not set up), an API error with "Try again", the "page not found" page, and an automatic accessibility check (axe, WCAG 2.1 A and AA) of every page. Automatic checks find only part of the accessibility problems; they do not replace a review with a screen reader.

To use another API address, copy `apps/web/.env.example` to `.env.local` and set `VITE_API_URL`. The API accepts browser calls only from the origins in `CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`).

Every page shows a **Simulated data** badge. The login token is kept for the browser tab only (`sessionStorage`). Each page has loading, error (with "Try again") and empty states.

**Screens.** Every list has filters where useful, paging with the total, and loading, error and empty states. Statuses are written out ("out of stock", "at risk"), so colour is never the only signal.

| Screen | What it shows | Actions |
|---|---|---|
| Overview | headline numbers from `GET /dashboard/kpis` | |
| Stock risks | every product at every warehouse: status, stock, on order, demand per day, reorder point, target, shortfall, days of cover | filter by warehouse and status |
| Recommendations | pending transfers and reorders with the numbers behind them (proposals only) | managers: make new recommendations at a chosen service level |
| Suppliers & orders | on-time ratings for 90 days; purchase orders with an overdue mark | managers: receive an open order |
| Forecasts | one M5 item at one M5 store: 28 days with the 80% range (chart + table), labelled as M5 data | choose store and item |
| Delivery risk | the day's late-delivery alerts with tier, probability and reasons, labelled as Olist data | choose a dispatch day |
| Ask the copilot | the answer, its checked citations, a "verified" or "not verified" mark, removed citations, limitations, and every step it took (tools used, tokens, time); earlier questions | ask a question (calls the AI provider; limited per hour) |
| Audit log | who did what and when, newest first (managers and admins) | filter by kind of record |
| Users | accounts (admins only) | add, change role, deactivate, set a temporary password |
| My account | your details | change your password |

**Accounts for real users.** There is no public sign-up: ChainPilot is an internal tool.
1. The first administrator is created on the server: `python -m app.cli create-user --email ... --full-name ... --role admin`.
2. An admin opens **Users** in the dashboard and adds each person with a role (analyst, manager or admin) and a temporary password.
3. The person logs in and changes the password on **My account**. This signs out their other sessions.
4. Someone who forgot their password asks an admin, who uses "Set temporary password". That signs the person out everywhere.

Admins can also change roles and deactivate or reactivate accounts. The dashboard does not offer a button to deactivate your own account, and the API refuses to remove the last active admin.

| Endpoint used by the overview | Who |
|---|---|
| `GET /dashboard/kpis`: products, warehouses, units and stock value; stock status counts (or why they are missing); pending reorders and transfers; open and overdue purchase orders; supplier ratings | analyst+ |
| `POST /auth/password` `{current_password, new_password}`: change your own password (a wrong current password counts as a failed login) | any logged-in user |
| `POST /users/{id}/password` `{new_password}`: set a temporary password and sign the user out everywhere | admin |

## Users, login and roles

| Role | Can |
|---|---|
| `analyst` | read data |
| `manager` | everything an analyst can, plus approve actions (later phases) |
| `admin` | everything a manager can, plus manage users |

| Endpoint | Who |
|---|---|
| `POST /auth/login` `{email, password}` returns `{access_token, expires_at, user}` | anyone |
| `GET /auth/me` | any logged-in user |
| `POST /auth/logout` (revokes the token) | any logged-in user |
| `GET /users?limit=&offset=`, `POST /users`, `PATCH /users/{id}` (role, name, active) | admin |
| `GET /audit-events?entity_type=&entity_id=&limit=&offset=` | manager, admin |

Send the token as `Authorization: Bearer <token>`. A missing, unknown, expired or revoked token gives **401**; a role that is too low gives **403**. Tokens last `ACCESS_TOKEN_TTL_MINUTES` (default 480 = 8 hours).

**Create the first admin** (prompts twice for the password; nothing is echoed or saved in shell history):

```bash
docker compose up -d
docker compose run --rm api python -m app.cli create-user --email you@example.com --full-name "Your Name" --role admin
```

How it is kept safe:
- Passwords are hashed with **scrypt** (Python standard library, OWASP-recommended settings, random salt per user) and must be 12–128 characters.
- Tokens are 256-bit random values. The database stores only their SHA-256 hash, so a leaked database does not leak usable tokens. Logout revokes a token immediately.
- Failed logins return the same message whether the email exists or not, and take about the same time either way.
- Emails are stored lower-case, so `Ana@X.com` and `ana@x.com` are the same account.
- Logs record user ids, never passwords, tokens or the emails used in failed attempts.
- **Rate limiting:** after 5 failed logins for one email (or 20 from one IP) within 15 minutes, login returns **429** with `Retry-After: 900`, even for the right password. The check runs before the slow password hash. A successful login resets that email's count, and blocks expire on their own.
- **Last admin protection:** the last active admin cannot be demoted or deactivated (409). The check locks the admin rows, so two admins demoting each other at the same moment cannot leave zero admins.
- Deactivating a user (`PATCH /users/{id}` with `{"is_active": false}`) blocks their login and stops their existing tokens immediately.

**Audit trail:** logins, logouts, user creation and user changes are written to `audit_events` (actor, action, entity, details such as `{"changes": {"role": ["analyst", "manager"]}}`) in the same transaction as the change itself. Stock movements record the acting user in `inventory_movements.created_by_user_id`.

**Client IP behind a proxy:** rate limiting uses the client's IP. Uvicorn takes the IP from `X-Forwarded-For` only when the request comes from an address in `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`), so clients cannot fake their IP. Behind the AWS load balancer (P8), set it to the load balancer's subnet.

**Housekeeping:** `docker compose run --rm api python -m app.cli cleanup --days 30` deletes tokens that expired or were revoked more than 30 days ago, and login attempts older than 30 days. Safe to run daily. What is kept and for how long: [docs/DATA_RETENTION.md](docs/DATA_RETENTION.md).

## Run locally with Docker

Requirements: Docker Desktop with Compose v2.

```bash
cp .env.example .env          # then edit POSTGRES_PASSWORD
docker compose up --build -d
curl http://127.0.0.1:8000/health   # {"status":"ok"}
curl http://127.0.0.1:8000/ready    # {"status":"ready","database":"ok"}
# the dashboard: http://127.0.0.1:8080
docker compose down                 # add -v to also delete the database volume
```

If port 5432 or 8000 is already used on your machine, change `POSTGRES_HOST_PORT` / `API_HOST_PORT` in `.env` (and `POSTGRES_PORT` to match if you run the API outside Docker).

**Database migrations** run automatically: `docker compose up` starts the `migrate` job (`alembic upgrade head`) and the API waits for it to finish. Useful commands:

```bash
docker compose run --rm migrate alembic current            # which revision the database is at
docker compose run --rm migrate alembic downgrade -1       # undo the latest migration
```

To create a new migration after changing `app/models.py`, run `alembic revision --autogenerate -m "describe change"` inside `apps/api` with the `POSTGRES_*` variables set, then **read and edit** the generated file before committing. The test `test_models_and_migrations_are_in_sync` fails if models and migrations disagree.

**Changing the password later:** Postgres sets the password only when it first creates its data volume. If you change `POSTGRES_PASSWORD` afterwards, `/ready` will return 503 until you recreate the volume with `docker compose down -v` (this deletes the local database).

## Run the API and tests without Docker

Requirements: Python 3.11.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r apps/api/requirements-dev.txt

cd apps/api
pytest                      # unit tests; database tests are skipped
ruff check . && ruff format --check .

# Run the API against the Compose Postgres (start it with: docker compose up -d migrate)
uvicorn app.main:app --reload --env-file ../../.env

# Database tests (need Postgres running and the POSTGRES_* variables set)
RUN_DB_TESTS=1 pytest
```

Database tests never touch your development data. Each run creates a throwaway database named `<POSTGRES_DB>_pytest_<random>`, applies the migrations, and drops it at the end. The `POSTGRES_USER` therefore needs permission to create databases (the Compose user has it).

## Configuration

All settings come from environment variables (see [.env.example](.env.example)). The database password is a separate variable, and the API builds the connection URL with SQLAlchemy's `URL.create()`, so passwords containing `@ : / # ?` work. Avoid `$` in passwords because Docker Compose treats it as variable interpolation.

- `POSTGRES_HOST` defaults to `127.0.0.1`, not `localhost`. On Windows, `localhost` tries IPv6 first, which stalls because Docker publishes the port on IPv4 only.
- `LOG_FORMAT=json` (default) prints one JSON object per line, which log tools like CloudWatch can search by field. Use `LOG_FORMAT=text` for easier reading while developing.

## Continuous integration

GitHub Actions runs [.github/workflows/ci.yml](.github/workflows/ci.yml) on every push to `main` and every pull request. It has five jobs:
1. **API lint and tests:** Python 3.11, Ruff, and pytest including the PostgreSQL integration tests (Postgres runs as a service container).
2. **ML lint and tests:** Ruff and pytest for `ml/`, using tiny synthetic files in the M5 format (the real dataset is never in CI).
3. **Web type-check, tests and build:** the dashboard's TypeScript check, unit tests and production build.
4. **Browser end-to-end tests:** `apps/web/e2e/run-e2e.sh` (above); the Playwright report is kept for 7 days when a test fails.
5. **Docker build and smoke test:** builds the stack with Compose, waits for the healthchecks, then curls `/health`, `/ready` and the dashboard (including a deep link) and checks that migrations ran.

The workflow has read-only permissions and uses no secrets; its database passwords are throwaway CI values.

## Design choices a student can defend

- **`/health` vs `/ready`:** liveness never touches the database, so a database outage doesn't make the orchestrator restart a healthy API process. Readiness does check the database, so traffic is only sent when the API can actually serve it.
- **Lazy database engine:** the engine is created on first use, so the API starts even if Postgres is still booting.
- **Localhost-only ports and a non-root container:** secure defaults for a laptop on shared Wi-Fi.
- **No Kafka, no Kubernetes:** the workload doesn't need them. AWS deployment will use ECS Fargate (later phase).

See [docs/DECISIONS.md](docs/DECISIONS.md) for the full list.
