# P8 — AWS staging deployment: plan and cost estimate

Status: **APPROVED for demo days only, region ap-south-1 (D-063).** P8-T1 (Terraform, checked offline) is written: `infrastructure/terraform/`. Nothing has been created in AWS yet.

Written 2026-10-17 by Claude Code. Prices are **approximate on-demand list prices for us-east-1** from third-party pricing pages (see Sources), not from AWS directly. Check them in the [AWS Pricing Calculator](https://calculator.aws/) before approving. Other regions are usually somewhat more expensive (for example Mumbai, ap-south-1).

## Goal (spec, P8 gate)

One **staging** environment in AWS, built with Terraform, deployed by GitHub Actions without stored AWS keys, with smoke tests, a rollback path, logs and alarms. It is not production, and it uses only the synthetic and public data the local stack already uses.

## Architecture (smallest setup that meets the spec)

```
Browser ──HTTPS──> CloudFront (https://<id>.cloudfront.net, free certificate)
                     ├── /*      -> S3 bucket (the built dashboard, private, CloudFront-only)
                     └── /api/*  -> (VPC origin, private) internal Load Balancer -> ECS Fargate: API container
                                                                  └── RDS PostgreSQL (private subnets)
Secrets Manager: database password, Groq key        CloudWatch: logs (14 days), alarms
ECR: API image                                       AWS Budgets: alerts at 50% / 80% / 100%
GitHub Actions --OIDC role--> deploy (no static AWS keys)
```

Why this shape:
- **One address for the dashboard and the API** (CloudFront). The login cookie is SameSite=Strict, so it then simply works (P7-T3-R1). The image no longer needs the API address built in (P6-T4-R4), and HTTPS comes with CloudFront's own domain, so the Secure cookie works without buying a domain.
- **Private path from CloudFront to the API:** the load balancer is internal (no public address) and CloudFront reaches it through a **VPC origin**, so requests never cross the public internet unencrypted (P8-T1-R1).
- **No NAT gateway** (about $33/month on its own). The API task runs in a public subnet with a public IP, so it can reach ECR, Groq and Secrets Manager. Its security group accepts traffic only from the load balancer. The database sits in private subnets and accepts connections only from the API's security group.
- **The dashboard as static files on S3 + CloudFront** instead of a second container: practically free at demo traffic.
- **Migrations** run as a one-off ECS task with the same image before each deploy (as the `migrate` service does locally).
- **No Kafka, no Kubernetes, no Bedrock.** The copilot keeps using Groq (owner's key, free tier).

## Monthly cost estimate (staging, running 24/7)

| Item | Size | ≈ USD / month |
|---|---|---|
| ECS Fargate (API) | 0.25 vCPU, 0.5 GB, x86 (builds natively in CI; ARM would save about $1.5), 1 task | 9 |
| RDS PostgreSQL 16 | db.t4g.micro, single-AZ, 20 GB gp3, 7-day backups | 14 |
| Application Load Balancer | 1 ALB, very low traffic | 18–22 |
| Public IPv4 addresses | API task (1), $0.005/hour; the load balancer is internal (no public IPs) | 4 |
| CloudFront + S3 | demo traffic (CloudFront has a free monthly allowance) | 0–1 |
| Secrets Manager | 2 secrets | 1 |
| CloudWatch | logs (14 days), a few alarms, 1 dashboard | 1–3 |
| ECR | a few images | < 1 |
| **Total** | | **≈ 47–55** (ap-south-1 somewhat more) |

How to spend much less:
- **Run it only when needed:** `terraform apply` before a demo, `terraform destroy` afterwards. Example: 3 days ≈ **$6**. The database is created again from the seed; staging keeps no data worth keeping.
- **Pause:** stop the ECS service (0 tasks) and the database (AWS restarts a stopped database after 7 days). The ALB and IPv4 addresses still cost about $27/month.
- **New-account credits:** accounts opened since July 2025 get $100, plus up to $100 more for onboarding tasks, which can cover this. The rules (expiry, Free vs Paid plan) differ between sources, so check yours in the Billing console.

Not included: a custom domain (optional, about $12/year), data transfer beyond demo use, and Groq or Gemini usage (billed by them; the free tier is used).

## Guardrails (from the spec)

- **No AWS action without your explicit approval.** First, a budget with email alerts at 50%, 80% and 100% of a limit you choose. Then `terraform plan`, whose output you read. Only then `apply`.
- GitHub Actions gets a role through **OIDC**, limited to this repository's `main` branch, so no AWS keys are stored in GitHub. Every resource is tagged `project=chainpilot-ai, env=staging`.
- Secrets live in Secrets Manager and are never in Terraform files, Git or logs. The Terraform state is kept in an S3 bucket with versioning and encryption, and a lock.
- Deletion protection is off for staging (so `destroy` works); production hardening is left for later.

## Tasks

| Task | What | Needs AWS? | Cost |
|---|---|---|---|
| P8-T1 | Terraform for everything above, written and checked offline (`terraform fmt`, `validate`, and `tflint` in CI). Small API/web changes for the `/api` path. | No | $0 |
| P8-T2 | Your AWS account: budget and alerts, Terraform state bucket, GitHub OIDC role (you run the commands or approve each one) | Yes | ≈ $0 |
| P8-T3 | `terraform plan` → your review → `apply` staging; deploy workflow (build, push, migrate, deploy); smoke tests against the real URL | Yes | from here on, the monthly cost above while it runs |
| P8-T4 | Rollback (previous task definition) tried for real once; CloudWatch alarms (5xx errors, CPU, database) and a dashboard; destroy and pause instructions | Yes | included |

If you do not approve cloud spending: P8-T1 is still done (free), and the deployment is marked **BLOCKED (no approval)** with the reproducible scripts, as the spec requires. Nothing will be described as deployed.

## Decisions needed from you

1. Approve the plan and the spending pattern (24/7 at ≈ $55/month, demo days only, or nothing yet).
2. Region: us-east-1 (cheapest, most services) or the one nearest to you (for example ap-south-1, Mumbai).
3. Do you have an AWS account you can use, with a billing alert email?
4. For P8-T1 I need the Terraform CLI (and later the AWS CLI) on this machine. Neither is installed. Installing them is free and changes nothing in AWS.

## Sources (prices, checked 2026-10-17)

- Fargate rates: [factualminds.com Fargate pricing 2026](https://www.factualminds.com/blog/amazon-fargate-ecs-task-pricing-2026/), [wring.co Fargate pricing guide](https://wring.co/blog/aws-fargate-pricing-guide)
- RDS db.t4g.micro: [Holori calculator](https://calculator.holori.com/aws/rds/db.t4g.micro), [Vantage instances](https://instances.vantage.sh/aws/rds/db.t4g.micro)
- New-account credits: [infratally.com: AWS Free Tier in 2026](https://infratally.com/articles/aws-free-tier-2026/), [Rackspace: AWS Free Tier explained](https://spot.rackspace.com/blog/aws-free-tier)
- ALB, public IPv4, Secrets Manager, CloudWatch: AWS list prices as known to me (no live check). Please confirm in the AWS Pricing Calculator.
