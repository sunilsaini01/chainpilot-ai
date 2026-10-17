# Staging environment for demo days (D-063): created before a demo, destroyed after.
# Plan: docs/AWS_PLAN.md. Nothing here holds a secret value: the database password
# is managed by RDS in Secrets Manager, the Groq key is put into its secret by hand.

terraform {
  required_version = ">= 1.16.5, < 1.17.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.67.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
  # Bucket and region come from backend.hcl (see backend.hcl.example), written
  # after the bootstrap step: terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "staging/terraform.tfstate"
    encrypt      = true
    use_lockfile = true # S3-native lock: two applies cannot run at once
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "chainpilot-ai", env = "staging", managed_by = "terraform" }
  }
}
