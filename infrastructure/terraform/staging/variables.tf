variable "region" {
  description = "AWS region (the owner chose Mumbai, D-063)."
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Prefix for resource names. IAM roles must start with chainpilot-staging- (bootstrap deploy role)."
  type        = string
  default     = "chainpilot-staging"
}

variable "api_image_tag" {
  description = "Tag of the API image in ECR to run (the deploy workflow passes the Git commit)."
  type        = string
  default     = "latest"
}

variable "api_desired_count" {
  description = "API tasks to run. 0 pauses the API (the load balancer and database still cost money)."
  type        = number
  default     = 1
}

variable "alert_email" {
  description = "Where CloudWatch alarms go (the address must confirm the SNS subscription email)."
  type        = string
}

variable "enable_copilot" {
  description = "Run the AI copilot. Needs the Groq key put into the secret <name>-groq-api-key first."
  type        = bool
  default     = false
}

variable "groq_model" {
  description = "Groq model id for the copilot (only used when enable_copilot is true)."
  type        = string
  default     = "qwen/qwen3.8-27b"
}

variable "db_instance_class" {
  description = "RDS instance size. db.t4g.micro is the smallest PostgreSQL 16 size."
  type        = string
  default     = "db.t4g.micro"
}
