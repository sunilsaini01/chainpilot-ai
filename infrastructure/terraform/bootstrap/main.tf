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
    # Only workflows on this repository's main branch can deploy.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "chainpilot-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# Broad on purpose for a demo staging account: Terraform in the deploy workflow
# creates and destroys the whole staging stack. Narrow it before any production use
# (noted in docs/AWS_PLAN.md and the review queue).
resource "aws_iam_role_policy_attachment" "deploy_admin" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "deploy_iam" {
  # PowerUserAccess excludes IAM; staging needs to create its own task roles,
  # limited here to roles whose names start with chainpilot-staging-.
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
