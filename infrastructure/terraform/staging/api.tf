# The API on ECS Fargate behind an Application Load Balancer.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name}-api"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = var.name
}

# --- Roles ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself to start the task: pull the image, write logs, read the secrets.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_db_instance.main.master_user_secret[0].secret_arn],
      aws_secretsmanager_secret.groq[*].arn,
    )
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

# The application's own role: it calls no AWS service, so it has no permissions.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# --- Task definition -------------------------------------------------------------------

locals {
  site_url = "https://${aws_cloudfront_distribution.main.domain_name}"
  # The RDS-managed secret is JSON; ":password::" picks one key from it.
  db_password_ref = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::"

  api_environment = concat(
    [
      { name = "ENVIRONMENT", value = "staging" }, # Secure cookie and HSTS (HTTPS only)
      { name = "LOG_FORMAT", value = "json" },
      { name = "POSTGRES_HOST", value = aws_db_instance.main.address },
      { name = "POSTGRES_PORT", value = tostring(aws_db_instance.main.port) },
      { name = "POSTGRES_USER", value = aws_db_instance.main.username },
      { name = "POSTGRES_DB", value = aws_db_instance.main.db_name },
      { name = "CORS_ORIGINS", value = local.site_url },
      # Trust X-Forwarded-For only from inside the VPC (the load balancer).
      { name = "FORWARDED_ALLOW_IPS", value = aws_vpc.main.cidr_block },
      { name = "LANGSMITH_TRACING", value = "false" },
      { name = "LLM_PROVIDER", value = "groq" },
    ],
    var.enable_copilot ? [{ name = "GROQ_MODEL", value = var.groq_model }] : [],
  )
  api_secrets = concat(
    [{ name = "POSTGRES_PASSWORD", valueFrom = local.db_password_ref }],
    [for secret in aws_secretsmanager_secret.groq : { name = "GROQ_API_KEY", valueFrom = secret.arn }],
  )
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256 # 0.25 vCPU
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  # The same image also runs one-off commands (migrations, seed, create-user) with
  # a command override: aws ecs run-task ... (see docs/AWS_RUNBOOK.md, P8-T3).
  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.api_environment
    secrets      = local.api_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

# --- Load balancer ---------------------------------------------------------------------

# Internal: no public address. Only CloudFront reaches it, through a VPC origin
# (web.tf), so requests from the edge into the VPC stay on AWS's private network.
resource "aws_lb" "api" {
  name               = "${var.name}-api"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.private[*].id
  idle_timeout       = 120 # a copilot question can take about a minute
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
  }
  deregistration_delay = 10 # demo traffic: no need to wait long for old tasks
}

# Plain HTTP inside the VPC only: the load balancer has no public address.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# --- Service -----------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # no NAT gateway: the task reaches AWS services and Groq directly
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  # Rollback: if a new version never becomes healthy, ECS returns to the last
  # working task definition by itself.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  health_check_grace_period_seconds = 30
  depends_on                        = [aws_lb_listener.http]
}
