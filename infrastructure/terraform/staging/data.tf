# Where the API image, the database and the secrets live.

resource "aws_ecr_repository" "api" {
  name                 = "${var.name}-api"
  image_tag_mutability = "IMMUTABLE" # a tag always means the same image (rollback is exact)
  force_delete         = true        # demo days only: destroy removes the images too
  image_scanning_configuration {
    scan_on_push = true # known vulnerabilities in the image are listed in ECR
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class
  db_name        = "chainpilot"
  username       = "chainpilot"
  # RDS creates the password and keeps it in Secrets Manager, so it never appears
  # in Terraform files or state. The API task reads it from that secret.
  manage_master_user_password = true

  allocated_storage      = 20
  storage_type           = "gp3"
  storage_encrypted      = true
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false # staging: one zone is enough

  backup_retention_period = 1
  # Demo days only: staging holds only seeded demo data, so destroy needs no snapshot.
  skip_final_snapshot = true
  deletion_protection = false
  apply_immediately   = true
}

# The Groq key for the copilot. Terraform creates the empty secret; the owner puts
# the value in (console or `aws secretsmanager put-secret-value`), so it is never in
# Terraform state. Only created when the copilot is switched on.
resource "aws_secretsmanager_secret" "groq" {
  count                   = var.enable_copilot ? 1 : 0
  name                    = "${var.name}-groq-api-key"
  recovery_window_in_days = 0 # demo days: destroy and create again without a 7-day wait
}

# Private bucket for data files to import (forecasts, delivery-risk scores). Kept
# apart from the dashboard bucket, which CloudFront serves publicly. The import task
# reads the files through short-lived presigned links (docs/AWS_RUNBOOK.md), so the
# API's task role needs no S3 permission.
resource "aws_s3_bucket" "imports" {
  bucket        = "${var.name}-imports-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # demo days only: the files are uploaded again from the owner's machine
}

resource "aws_s3_bucket_public_access_block" "imports" {
  bucket                  = aws_s3_bucket.imports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
