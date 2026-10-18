# One-time setup in the owner's AWS account (P8-T2), applied by the owner:
# - the S3 bucket that keeps the staging Terraform state (versioned, encrypted, private);
# - the GitHub OIDC provider and a deploy role that only this repository's main
#   branch can assume, so no AWS keys are stored in GitHub;
# - a monthly budget that emails at 50%, 80% and 100% of the limit.
# Its own state stays on the owner's machine (terraform.tfstate, ignored by Git):
# it holds no secrets, and it is needed only to change or remove these resources.

terraform {
  required_version = ">= 1.16.5, < 1.17.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.67.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "chainpilot-ai", env = "shared", managed_by = "terraform" }
  }
}

data "aws_caller_identity" "current" {}

# --- Terraform state bucket --------------------------------------------------------

resource "aws_s3_bucket" "state" {
  # The account id makes the name unique worldwide without a random suffix.
  bucket = "chainpilot-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled" # an overwritten state can be recovered
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- GitHub Actions deploy role (OIDC) -----------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only the deploy workflow's two GitHub environments can assume the role:
    # "staging-plan" (build and plan) and "staging" (apply, after the owner approves).
    # Both are limited to the main branch in the repository settings (docs/AWS_RUNBOOK.md).
    # GitHub names the repository with its permanent ids (owner@id/name@id), seen in
    # CloudTrail on the first run, so a re-created repository of the same name is refused.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository_subject}:environment:staging-plan",
        "repo:${var.github_repository_subject}:environment:staging",
      ]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "chainpilot-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# What the deploy workflow may do: only the services staging uses (P8-T1-R2; it
# replaced PowerUserAccess). Regional services only in the chosen region, S3 only
# on chainpilot buckets, IAM only on chainpilot-staging-* roles (below).
data "aws_iam_policy_document" "deploy" {
  statement {
    sid = "StagingServicesInTheRegion"
    actions = [
      "ec2:*", "elasticloadbalancing:*", "ecs:*", "ecr:*", "rds:*",
      "secretsmanager:*", "logs:*", "cloudwatch:*", "sns:*", "kms:DescribeKey",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }
  statement {
    sid       = "ProjectBucketsOnly"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::chainpilot-*", "arn:aws:s3:::chainpilot-*/*"]
  }
  statement {
    # CloudFront is a global service (no region); identity lookups too.
    sid       = "GlobalServices"
    actions   = ["cloudfront:*", "sts:GetCallerIdentity"]
    resources = ["*"]
  }
  statement {
    # ECS, the load balancer and RDS create their own service roles on first use.
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values = [
        "ecs.amazonaws.com", "elasticloadbalancing.amazonaws.com", "rds.amazonaws.com",
      ]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "staging-services"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

data "aws_iam_policy_document" "deploy_iam" {
  # Staging creates its own task roles, limited to names starting with chainpilot-staging-.
  statement {
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:PassRole", "iam:TagRole",
      "iam:UntagRole", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListInstanceProfilesForRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/chainpilot-staging-*"]
  }
}

resource "aws_iam_role_policy" "deploy_iam" {
  name   = "staging-roles-only"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_iam.json
}

# --- Budget ------------------------------------------------------------------------

resource "aws_budgets_budget" "monthly" {
  name         = "chainpilot-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
  # Also warn early when the month is forecast to go over the limit.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
