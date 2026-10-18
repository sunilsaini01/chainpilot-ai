# AWS staging runbook (demo days)

Staging runs only when needed (D-063): create it before a demo, destroy it afterwards. Region ap-south-1. Costs about $1.5–2 a day while it exists (docs/AWS_PLAN.md), paid from the account's credits; a $15/month budget alert emails the owner.

All commands run from the repository root in PowerShell or Git Bash, after `aws login --region ap-south-1` (the login lasts about 12 hours).

## Before the first deploy (done once, 2026-10-18)
- `infrastructure/terraform/bootstrap` applied: the state bucket, the GitHub deploy role, the budget.
- `infrastructure/terraform/staging/backend.hcl` written from the bootstrap output `state_bucket`. Git ignores it.
- The account needed a payment method (UPI AutoPay) before S3 worked, and an AWS Support check before CloudFront worked (both one-time, see the work log).

## Create or update staging
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
5. **Smoke test:** `python infrastructure/scripts/smoke-test.py <site_url> admin@example.com '<password>'` must report all checks passed.

## Pause (keeps the data, still about $1/day)
`terraform apply -var "api_desired_count=0" ...` stops the API. The database and load balancer keep running. For a longer break, destroy instead.

## Destroy (stops all costs; the data is lost, staging is demo data only)
In `infrastructure/terraform/staging`: `terraform destroy -var "alert_email=<owner email>" -var "api_image_tag=<tag>"`. Read the list, then type `yes`. The registry images and the dashboard files are deleted too (`force_delete` / `force_destroy`). The bootstrap resources (state bucket, deploy role, budget) stay; they cost nothing or almost nothing.

## Rollback
- Automatic: the ECS deployment circuit breaker returns to the last working task definition if a new one never becomes healthy.
- By hand: apply again with the previous image tag (`-var "api_image_tag=<previous tag>"`). ECR tags are immutable, so the old tag is exactly the old image.
