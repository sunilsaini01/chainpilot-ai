output "state_bucket" {
  description = "Put this in staging/backend.hcl (bucket = ...)."
  value       = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  description = "Put this in the GitHub repository variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.deploy.arn
}
