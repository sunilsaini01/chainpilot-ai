output "site_url" {
  description = "The dashboard (and /api/... for the API)."
  value       = local.site_url
}

output "ecr_repository_url" {
  description = "Where the deploy workflow pushes the API image."
  value       = aws_ecr_repository.api.repository_url
}

output "web_bucket" {
  description = "Where the deploy workflow uploads the built dashboard."
  value       = aws_s3_bucket.web.bucket
}

output "cloudfront_distribution_id" {
  description = "For cache invalidation after uploading a new dashboard."
  value       = aws_cloudfront_distribution.main.id
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}

output "api_task_definition" {
  description = "Also used for one-off commands (migrations, seed, create-user)."
  value       = aws_ecs_task_definition.api.arn
}

output "task_network" {
  description = "Subnets and security group for one-off tasks (aws ecs run-task)."
  value = {
    subnets         = aws_subnet.public[*].id
    security_groups = [aws_security_group.api.id]
  }
}

output "imports_bucket" {
  description = "Private bucket for data files to import (see docs/AWS_RUNBOOK.md)."
  value       = aws_s3_bucket.imports.bucket
}
