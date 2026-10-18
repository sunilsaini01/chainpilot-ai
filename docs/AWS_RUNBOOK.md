# AWS staging runbook (demo days)

Staging runs only when needed (D-063): create it before a demo, destroy it afterwards. Region ap-south-1. Costs about $1.5–2 a day while it exists (docs/AWS_PLAN.md), paid from the account's credits; a $15/month budget alert emails the owner.

All commands run from the repository root in PowerShell or Git Bash, after `aws login --region ap-south-1` (the login lasts about 12 hours).

## Before the first deploy (done once, 2026-10-18)
- `infrastructure/terraform/bootstrap` applied: the state bucket, the GitHub deploy role, the budget.
- `infrastructure/terraform/staging/backend.hcl` written from the bootstrap output `state_bucket`. Git ignores it.
- The account needed a payment method (UPI AutoPay) before S3 worked, and an AWS Support check before CloudFront worked (both one-time, see the work log).

## Deploy from GitHub (normal way, after the first creation)
GitHub → **Actions** → **Deploy staging** → **Run workflow** (branch `main`).
1. Job **Build image and plan** builds and pushes the API image for the commit and shows the Terraform plan in the run summary.
2. Job **Apply, migrate, upload, smoke test** waits for approval in the protected `staging` environment. Read the plan, then **Review deployments → Approve**. The job applies only if a fresh plan has the same summary line as the approved one, then waits for ECS, migrates the database, uploads the dashboard and runs the smoke tests (no login).

One-time GitHub settings (done by the owner): repository **variables** `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET` and `ALERT_EMAIL` (from the bootstrap outputs); **environments** `staging-plan` and `staging`, both limited to the `main` branch, and `staging` with the owner as required reviewer. The AWS role trusts only these two environments (bootstrap). The workflow cannot create staging from nothing (the image registry must exist first); use the manual steps below for that.

## Create or update staging by hand
1. **Image** (tag = the Git commit):
   ```bash
   TAG=$(git rev-parse --short HEAD)
   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   REG=$ACCOUNT.dkr.ecr.ap-south-1.amazonaws.com
   aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin $REG
   docker build --platform linux/amd64 -t $REG/chainpilot-staging-api:$TAG apps/api
   docker push $REG/chainpilot-staging-api:$TAG
   ```
   On a brand-new staging, the registry must exist first: `terraform apply -target=aws_ecr_repository.api -target=aws_ecr_lifecycle_policy.api` (in `infrastructure/terraform/staging`, with the variables below).
2. **Infrastructure:** in `infrastructure/terraform/staging`:
   ```bash
   terraform init -backend-config=backend.hcl
   terraform plan -var "alert_email=<owner email>" -var "api_image_tag=$TAG" -out=staging.tfplan
   terraform apply staging.tfplan
   ```
   Read the plan before applying. A new staging shows 47 to add; an image update shows the task definition replaced and the service updated. ECS rolls back by itself if the new version never becomes healthy.
3. **Dashboard:** build with the API on the same address and upload:
   ```bash
   cd apps/web && MSYS_NO_PATHCONV=1 VITE_API_URL=/api npx vite build --outDir ../../build/web-staging --emptyOutDir && cd ../..
   aws s3 sync build/web-staging/assets s3://<web_bucket>/assets --cache-control "public, max-age=31536000, immutable"
   aws s3 cp build/web-staging/index.html s3://<web_bucket>/index.html --cache-control no-store --content-type "text/html; charset=utf-8"
   MSYS_NO_PATHCONV=1 aws cloudfront create-invalidation --distribution-id <cloudfront_distribution_id> --paths "/*"
   ```
   `MSYS_NO_PATHCONV=1` matters in Git Bash: without it, `/api` is turned into `C:/Program Files/Git/api` and every API call fails.
4. **Database** (one-off ECS tasks; `TERRAFORM` = the path to terraform.exe if it is not on PATH):
   ```bash
   bash infrastructure/scripts/run-task.sh alembic upgrade head
   bash infrastructure/scripts/run-task.sh python -m app.cli seed           # new staging only
   bash infrastructure/scripts/run-task.sh python -m app.cli load-policies
   EXTRA_ENV_NAME=CHAINPILOT_NEW_USER_PASSWORD EXTRA_ENV_VALUE='<temporary password>' \
     bash infrastructure/scripts/run-task.sh python -m app.cli create-user --email admin@example.com --full-name "<name>" --role admin
   ```
   The temporary password is visible in the ECS task details for a while: change it under **My account** after the first login.
5. **Demo data** (forecasts and delivery-risk scores from the owner's machine; staging does not train models):
   ```bash
   B=$(terraform -chdir=infrastructure/terraform/staging output -raw imports_bucket)
   aws s3 sync data/processed/forecasts/m5_lightgbm_weekly_2016-04-24 s3://$B/forecasts/m5_lightgbm_weekly_2016-04-24
   aws s3 sync data/processed/delivery_risk/olist_logistic_2018-04-02_2018-08-31 s3://$B/delivery_risk/olist_logistic_2018-04-02_2018-08-31
   bash infrastructure/scripts/import-from-s3.sh import-forecasts forecasts/m5_lightgbm_weekly_2016-04-24
   bash infrastructure/scripts/import-from-s3.sh import-delivery-risk delivery_risk/olist_logistic_2018-04-02_2018-08-31
   bash infrastructure/scripts/run-task.sh python -m app.cli link-demand-profiles
   ```
   The imports bucket is private (not the dashboard bucket, which CloudFront serves). The import task gets 1 vCPU and 4 GB for the 850,000-row forecast file.
6. **Copilot (optional):** apply once with `-var "enable_copilot=true" -target=aws_secretsmanager_secret.groq` to create the empty secret. The owner then puts the Groq key into `chainpilot-staging-groq-api-key` (Secrets Manager → **Plaintext** tab, only the `gsk_…` value; **not** Key/value, which stores JSON and makes Groq answer "Invalid API Key"). Then apply again with `enable_copilot=true`. The API reads the secret when it starts: after changing the value, run `aws ecs update-service --cluster chainpilot-staging --service chainpilot-staging-api --force-new-deployment`.
7. **Smoke test:** `python infrastructure/scripts/smoke-test.py <site_url> admin@example.com '<password>'` must report all checks passed.

## Pause (keeps the data, still about $1/day)
`terraform apply -var "api_desired_count=0" ...` stops the API. The database and load balancer keep running. For a longer break, destroy instead.

## Destroy (stops all costs; the data is lost, staging is demo data only)
In `infrastructure/terraform/staging`: `terraform destroy -var "alert_email=<owner email>" -var "api_image_tag=<tag>"`. Read the list, then type `yes`. The registry images and the dashboard files are deleted too (`force_delete` / `force_destroy`). The bootstrap resources (state bucket, deploy role, budget) stay; they cost nothing or almost nothing.

## Watching it
- **Dashboard:** CloudWatch → Dashboards → `chainpilot-staging` (traffic, errors, response time, healthy tasks, API CPU and memory, database).
- **Alarms** email the owner (5xx errors, no healthy API task, API CPU, database CPU, low database storage). To test the email path: `aws cloudwatch set-alarm-state --alarm-name chainpilot-staging-db-cpu --state-value ALARM --state-reason test`. CloudWatch sets it back to OK at the next evaluation and emails again.
- **Logs:** CloudWatch → Log groups → `/ecs/chainpilot-staging-api` (14 days).

## Rollback
- Automatic: the ECS deployment circuit breaker returns to the last working task definition if a new one never becomes healthy. Tested 2026-10-18: an image that does not exist was rolled back after 3 failed tasks (about 13 minutes), and the site answered 77 of 77 health checks meanwhile.
- By hand: apply again with the previous image tag (`-var "api_image_tag=<previous tag>"`). ECR tags are immutable, so the old tag is exactly the old image. Tested 2026-10-18: back to `6b5bde4` and forward to `b245fa0`, each stable in under 3 minutes, with smoke tests 12/12.
