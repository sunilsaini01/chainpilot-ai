variable "region" {
  description = "AWS region for the state bucket (the owner chose Mumbai, D-063)."
  type        = string
  default     = "ap-south-1"
}

variable "github_repository_subject" {
  description = "The repository as GitHub's OIDC token names it: owner@owner_id/name@repo_id."
  type        = string
  default     = "sunilsaini01@242772514/chainpilot-ai@1420463207"
}

variable "alert_email" {
  description = "Where budget alerts go. Given at apply time, not stored in Git."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost limit for the alerts (demo days only: a few dollars a month)."
  type        = number
  default     = 15
}
