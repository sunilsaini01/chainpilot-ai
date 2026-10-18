# Architecture

ChainPilot AI has four parts: an **API** (FastAPI + PostgreSQL) that owns all data and rules, a **dashboard** (React) that only shows and asks, **ML pipelines** that run offline and hand over validated files, and an **AI copilot** inside the API that can read but never change anything. Design decisions are numbered in [DECISIONS.md](DECISIONS.md) (D-xxx below).

## Local stack (Docker Compose)

```mermaid
flowchart LR
  browser["Browser"] -->|"pages (127.0.0.1:8080)"| web["web: nginx<br/>built React dashboard"]
  browser -->|"API calls with the login cookie<br/>(127.0.0.1:8000)"| api["api: FastAPI<br/>rules, roles, audit"]
  api --> db[("postgres:<br/>PostgreSQL 16")]
  migrate["migrate: Alembic<br/>(runs once)"] --> db
  api -->|"copilot questions only"| llm["Groq API<br/>(owner's key)"]
  ml["ml/ pipelines<br/>(run by hand, offline)"] -->|"validated files<br/>(forecasts, risk scores)"| cli["python -m app.cli<br/>import-…"]
  cli --> db
```

- The browser talks to the API directly; the API allows only the listed origins (CORS) and checks the CSRF token on changes (D-061).
- The ML code never runs inside the API. It writes a folder with a manifest and a checksum, and the API imports it after checking every row (D-039, D-043).

## AWS staging (demo days only, ap-south-1)

```mermaid
flowchart LR
  user["Browser"] -->|HTTPS| cf["CloudFront<br/>(*.cloudfront.net)"]
  cf -->|"/* (private, OAC)"| s3["S3: dashboard files"]
  cf -->|"/api/* (VPC origin, private)"| alb["Internal load balancer"]
  alb --> ecs["ECS Fargate:<br/>API task"]
  ecs --> rds[("RDS PostgreSQL<br/>private subnets")]
  ecs -->|"secrets at start"| sm["Secrets Manager:<br/>DB password, Groq key"]
  ecs --> cw["CloudWatch:<br/>logs, alarms, dashboard"]
  cw -->|email| owner["Owner"]
  gh["GitHub Actions<br/>Deploy staging"] -->|"OIDC role, after approval"| ecr["ECR: API image"]
  gh -->|"terraform apply"| cf
  ecr --> ecs
```

- **One address** for the dashboard and the API (CloudFront), so the SameSite=Strict cookie works, and HTTPS needs no domain (D-064).
- The load balancer has **no public address**; CloudFront reaches it through a VPC origin (D-065). The database accepts connections only from the API.
- No NAT gateway: the API task has a public IP but accepts traffic only from the load balancer.
- Deploys: plan, the owner's approval in a protected GitHub environment, apply, migrate, upload, smoke test (D-066). The ECS circuit breaker rolls a broken version back by itself (tested, [AWS_RUNBOOK.md](AWS_RUNBOOK.md)).

## Request flow: approving a recommendation

```mermaid
sequenceDiagram
  participant M as Manager (browser)
  participant A as API
  participant D as PostgreSQL
  M->>A: POST /inventory/recommendations/{id}/decision<br/>cookie + X-CSRF-Token + Idempotency-Key
  A->>A: role ≥ manager? CSRF token matches?
  A->>D: lock the recommendation row (FOR UPDATE)
  A->>D: same key already used? → return the stored decision
  A->>D: still pending? (otherwise 409)
  alt reorder
    A->>D: create purchase order PO-REC-…
  else transfer
    A->>D: stock out of the source and into the destination<br/>(ledger, savepoint)
  end
  A->>D: decision + audit events, one transaction
  A-->>M: 201 with the outcome (executed or failed)
```

The row lock stops two managers acting at once; the idempotency key makes a retried click safe; everything is one transaction, so there is no half-done approval (D-059).

## Request flow: a copilot question

```mermaid
flowchart TD
  q["Question (analyst or higher,<br/>limited per hour)"] --> sup["Supervisor<br/>(LangGraph)"]
  sup --> spec["Specialists: demand, inventory,<br/>supplier, decision"]
  spec -->|"typed tools"| tools["Read-only tools<br/>(READ ONLY transaction, 5 s timeout)"]
  tools --> db[("PostgreSQL")]
  sup -->|"enough evidence"| answer["Answer with citations"]
  answer --> verify["Verify (code, not the model):<br/>every citation must come from a tool result"]
  verify --> out["Stored run: answer, verified mark,<br/>removed citations, full trace"]
```

The model can only call the listed tools, and the database itself refuses writes in those transactions. An answer whose citations were not returned by a tool is marked "not verified" (D-050, D-051, D-053).

## Where things live

| Part | Code | More |
|---|---|---|
| API, rules, roles, audit | `apps/api/app/` | [REFERENCE.md](REFERENCE.md) |
| Database schema | `apps/api/app/models.py`, `apps/api/migrations/` | migrations 0001–0012 |
| Dashboard | `apps/web/src/` | browser tests in `apps/web/e2e/` |
| Demand forecasting | `ml/demand_forecasting/` | [MODEL_RESULTS.md](MODEL_RESULTS.md) |
| Delivery risk | `ml/delivery_risk/` | [MODEL_RESULTS.md](MODEL_RESULTS.md) |
| Inventory replay | `ml/inventory_sim/` | [MODEL_RESULTS.md](MODEL_RESULTS.md) |
| Copilot | `apps/api/app/copilot/` | [REFERENCE.md](REFERENCE.md) |
| AWS | `infrastructure/terraform/`, `.github/workflows/deploy-staging.yml` | [AWS_PLAN.md](AWS_PLAN.md), [AWS_RUNBOOK.md](AWS_RUNBOOK.md) |
