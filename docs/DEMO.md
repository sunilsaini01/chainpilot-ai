# ChainPilot AI — 10-minute demo

A walkthrough for showing the project to a reviewer, a class or an interviewer. Every number below comes from the demo data (seed 42, the M5 forecasts and the Olist scores), so the same setup always shows the same numbers on the day it is loaded. The supplier dates follow the day of the seed.

**Say this first:** all operational data is **simulated** (the "Simulated data" badge, SYN- codes). Demand comes from the public **M5 (Walmart)** dataset, borrowed for the simulated products. Delivery risk is a separate experiment on public **Olist** orders from 2018. ChainPilot has no access to any real company's supply chain.

## Set up (about 10 minutes, once)

Local (free):
```bash
cp .env.example .env               # set POSTGRES_PASSWORD; GROQ_API_KEY + GROQ_MODEL for the copilot
docker compose up -d --build
bash scripts/demo-setup.sh         # Git Bash on Windows; safe to run again
```
The script prints three logins (`demo-admin`, `demo-manager`, `demo-analyst` @example.com) **once**. The forecasts and scores come from `data/processed/` (see docs/DATASETS.md); without them it uses the small synthetic test forecasts, and the numbers differ from the ones below.

AWS staging: see docs/AWS_RUNBOOK.md (about $1.5–2 a day while it exists; destroy it after the demo).

Open http://127.0.0.1:8080 (local) or the staging address.

## The walkthrough

| Min | Log in as | Show | Say | You should see |
|---|---|---|---|---|
| 0–1 | — | The login page | Accounts are made by an admin; there is no public sign-up. Sessions are httpOnly cookies with CSRF protection. | "Simulated data" badge |
| 1–2 | analyst | **Overview** | One page of headline numbers from the API. | 200 products, 4 warehouses; stock: 146 out of stock, 24 at risk, 88 ok, 542 excess (the seed overstocks on purpose) |
| 2–3 | analyst | **Stock risks** → warehouse SYN-WH1, status "out of stock" | For each product at each warehouse: stock + open orders against the reorder point and target from a forecast-driven formula (95% service level). | Rows with shortfall and days of cover; most urgent first |
| 3–4 | analyst | **Forecasts** → CA_1, FOODS_3_090 | A LightGBM model trained on M5, with an 80% range; tested in rolling backtests (docs/MODEL_RESULTS.md). | 28-day chart with the band, labelled M5 |
| 4–5 | analyst | **Suppliers & orders** | On-time rating over 90 days; overdue open orders are marked. | One supplier "at risk", some "watch" |
| 5–6 | analyst | **Ask the copilot** → "Which suppliers are unreliable, and which of their purchase orders are overdue?" | A LangGraph supervisor sends the question to specialist agents that may only call read-only tools; every claim must cite a record or policy, and citations are checked against the tool results. | An answer marked **Verified**, with citations; open "How it was answered" to show the steps |
| 6–8 | manager | **Approval queue** → **Make new recommendations**, then approve one reorder and one transfer, reject one with a reason | Nothing is ordered or moved until a manager approves. Approving carries it out (simulated): a reorder becomes a purchase order, a transfer moves stock. Two managers cannot approve the same proposal twice, and a lost click is safe to repeat (idempotency key). | 174 proposals (150 transfers, 24 reorders); "purchase order PO-REC-… placed"; "stock moved" |
| 8–9 | manager | **Audit log** → kind "recommendation", then "purchase_order" | Every change is recorded with who and when; records are never edited. | `recommendation.approved` / `rejected` and `purchase_order.created` with the manager's email |
| 9–10 | analyst | Try **Approval queue** as analyst; mention **Users** (admin only) | Roles are checked by the API on every endpoint; the screens only follow it (a test checks all 43 endpoints against every role). | No approve buttons; "Only managers and administrators can approve" |

Optional (AWS, 2 minutes): the CloudFront address with HTTPS, the GitHub **Deploy staging** workflow (plan → approval → apply), and the CloudWatch dashboard `chainpilot-staging`.

## If something goes wrong

- **The copilot says "At most 20 investigations per hour"** or Groq is slow: Groq's free tier limits tokens per minute. Wait a minute, or show an earlier question under "Earlier questions".
- **"Too many failed login attempts"**: 5 wrong passwords for one email lock it for 15 minutes (by design). Use another demo login, or wait.
- **Numbers differ from the table**: the seed's order dates follow the day it was loaded, and recommendations change after approvals. For a clean start: `docker compose down -v`, then `docker compose up -d --build` and the setup script again (this deletes the local database).
- **Lost the demo passwords**: an admin sets a temporary one on the **Users** page.

## Honest limitations to mention when asked

The data is simulated or public; the demand link between M5 items and simulated products is borrowed, not learned. Delivery risk is evaluated on Olist, not on the simulated suppliers. Transfers arrive instantly (no travel time). The copilot can be wrong in ways the checks do not catch (docs/REVIEW_QUEUE.md lists what is open). Staging is a demo environment, not production.
