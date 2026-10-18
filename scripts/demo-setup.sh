#!/usr/bin/env bash
# Sets up the ChainPilot demo on the local Docker Compose stack (docs/DEMO.md).
# Safe to run again: steps that are already done are skipped, nothing is loaded twice.
#
#   docker compose up -d --build      # the stack must be running
#   bash scripts/demo-setup.sh        # Git Bash on Windows
#
# Loads: migrations, the synthetic operations data (seed 42), the M5 forecasts and
# Olist delivery-risk scores from data/processed/ (the synthetic test forecasts if
# M5 is not there), the demand-profile links, the policy documents, and three demo
# users (admin, manager, analyst) with fresh random passwords, printed once at the end.
# DEMO_COMPOSE_ARGS: extra `docker compose` options (a throwaway project, for tests).
set -euo pipefail

cd "$(dirname "$0")/.."
compose() { docker compose ${DEMO_COMPOSE_ARGS:-} "$@"; }
# `pwd -W` gives a Windows path in Git Bash (for the -v mounts); plain pwd elsewhere.
root="$(pwd -W 2>/dev/null || pwd)"
created_users=()

# Runs one step. Treats an "already ..." answer as done, stops on any other error.
step() {
  local label=$1
  shift
  local output
  if output=$("$@" 2>&1); then
    # The first real line of output: not JSON log lines, not Docker's own messages.
    local result
    result=$(echo "$output" | grep -v -e '^{' -e '^ *Container ' -e '^ *Network ' | head -1 || true)
    echo "✓ $label${result:+: $result}"
  elif echo "$output" | grep -qi "already"; then
    echo "- $label: already done"
  else
    echo "$output"
    echo "✗ $label failed"
    exit 1
  fi
}

cli() { compose run --rm -T api python -m app.cli "$@"; }

# Runs a CLI import with a local folder mounted read-only into the container.
cli_with_folder() {
  local folder=$1
  shift
  MSYS_NO_PATHCONV=1 compose run --rm -T -v "$root/$folder:/import:ro" api python -m app.cli "$@" /import
}

step "database migrations" compose run --rm -T migrate alembic upgrade head
step "synthetic operations data (seed 42)" cli seed

forecasts=data/processed/forecasts/m5_lightgbm_weekly_2016-04-24
if [ -f "$forecasts/manifest.json" ]; then
  step "M5 demand forecasts" cli_with_folder "$forecasts" import-forecasts
else
  echo "  (no M5 forecasts in $forecasts: using the SYNTHETIC test forecasts instead)"
  step "synthetic test forecasts" cli_with_folder apps/web/e2e/fixtures/forecasts import-forecasts
fi

scores=data/processed/delivery_risk/olist_logistic_2018-04-02_2018-08-31
if [ -f "$scores/manifest.json" ]; then
  step "Olist delivery-risk scores" cli_with_folder "$scores" import-delivery-risk
else
  echo "  (no Olist scores in $scores: the Delivery risk page will say none are imported)"
fi

step "demand-profile links" cli link-demand-profiles
step "policy documents" cli load-policies

for role in admin manager analyst; do
  password="Demo-$(head -c 15 /dev/urandom | base64 | tr -d '/+=')"
  label="user demo-$role@example.com"
  if output=$(CHAINPILOT_NEW_USER_PASSWORD="$password" compose run --rm -T -e CHAINPILOT_NEW_USER_PASSWORD api \
    python -m app.cli create-user --email "demo-$role@example.com" --full-name "Demo ${role^}" --role "$role" 2>&1); then
    echo "✓ $label"
    created_users+=("demo-$role@example.com  $password")
  elif echo "$output" | grep -qi "already exists"; then
    echo "- $label: already exists (password unchanged; an admin can set a new one on the Users page)"
  else
    echo "$output"
    echo "✗ $label failed"
    exit 1
  fi
done

echo
echo "Demo ready: open http://127.0.0.1:8080 (or the dev server at http://127.0.0.1:5173)."
if [ ${#created_users[@]} -gt 0 ]; then
  echo "New demo logins (shown only now; keep them somewhere safe):"
  printf '  %s\n' "${created_users[@]}"
fi
