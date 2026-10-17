# Alarms by email. The address gets a confirmation email from AWS first.

resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarms = {
    api-5xx = {
      description = "The API answered with server errors (5xx)"
      namespace   = "AWS/ApplicationELB"
      metric      = "HTTPCode_Target_5XX_Count"
      statistic   = "Sum"
      threshold   = 5
      dimensions  = { LoadBalancer = aws_lb.api.arn_suffix }
    }
    api-unhealthy = {
      description = "No healthy API task behind the load balancer"
      namespace   = "AWS/ApplicationELB"
      metric      = "HealthyHostCount"
      statistic   = "Minimum"
      threshold   = 1
      comparison  = "LessThanThreshold"
      dimensions  = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
    }
    api-cpu = {
      description = "API tasks above 80% CPU"
      namespace   = "AWS/ECS"
      metric      = "CPUUtilization"
      statistic   = "Average"
      threshold   = 80
      dimensions  = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.api.name }
    }
    db-cpu = {
      description = "Database above 80% CPU"
      namespace   = "AWS/RDS"
      metric      = "CPUUtilization"
      statistic   = "Average"
      threshold   = 80
      dimensions  = { DBInstanceIdentifier = aws_db_instance.main.identifier }
    }
    db-storage = {
      description = "Database has less than 2 GB free"
      namespace   = "AWS/RDS"
      metric      = "FreeStorageSpace"
      statistic   = "Minimum"
      threshold   = 2 * 1024 * 1024 * 1024
      comparison  = "LessThanThreshold"
      dimensions  = { DBInstanceIdentifier = aws_db_instance.main.identifier }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "main" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  threshold           = each.value.threshold
  comparison_operator = lookup(each.value, "comparison", "GreaterThanThreshold")
  dimensions          = each.value.dimensions
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching" # no traffic on a quiet demo day is not an error
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
