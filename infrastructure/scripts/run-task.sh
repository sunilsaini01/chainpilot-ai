#!/usr/bin/env bash
# Runs one command in the staging API image as a one-off ECS task, waits for it,
# then prints its exit code and its log. Used for migrations, the seed, policies
# and creating users (docs/AWS_RUNBOOK.md).
# Usage: bash infrastructure/scripts/run-task.sh alembic upgrade head
#        EXTRA_ENV_NAME=... EXTRA_ENV_VALUE=... bash ... python -m app.cli create-user ...
set -euo pipefail

cd "$(dirname "$0")/../terraform/staging"
tf() { "${TERRAFORM:-terraform}" "$@"; }  # TERRAFORM: path if not on PATH
cluster=$(tf output -raw ecs_cluster)
task_definition=$(tf output -raw api_task_definition)
subnets=$(tf output -json task_network | python -c "import json,sys; print(','.join(json.load(sys.stdin)['subnets']))")
groups=$(tf output -json task_network | python -c "import json,sys; print(','.join(json.load(sys.stdin)['security_groups']))")

# The command as a JSON list, e.g. ["alembic","upgrade","head"].
command_json=$(python -c "import json,sys; print(json.dumps(sys.argv[1:]))" "$@")
environment="[]"
if [ -n "${EXTRA_ENV_NAME:-}" ]; then
  # Visible in the ECS task details for a while: only for temporary values.
  environment=$(python -c "import json,sys; print(json.dumps([{'name': sys.argv[1], 'value': sys.argv[2]}]))" \
    "$EXTRA_ENV_NAME" "$EXTRA_ENV_VALUE")
fi
overrides=$(python -c "import json,sys; print(json.dumps({'containerOverrides': [{'name': 'api', 'command': json.loads(sys.argv[1]), 'environment': json.loads(sys.argv[2])}]}))" \
  "$command_json" "$environment")

task_arn=$(MSYS_NO_PATHCONV=1 aws ecs run-task --cluster "$cluster" --task-definition "$task_definition" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$groups],assignPublicIp=ENABLED}" \
  --overrides "$overrides" --query "tasks[0].taskArn" --output text)
echo "Started: $*"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"

exit_code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query "tasks[0].containers[0].exitCode" --output text)
reason=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
  --query "tasks[0].stoppedReason" --output text)
task_id="${task_arn##*/}"
echo "--- log ---"
MSYS_NO_PATHCONV=1 aws logs get-log-events --log-group-name "/ecs/chainpilot-staging-api" \
  --log-stream-name "api/api/$task_id" --query "events[].message" --output text 2>/dev/null | tr '\t' '\n' | tail -30 || true
echo "--- exit code: $exit_code ($reason) ---"
[ "$exit_code" = "0" ]
