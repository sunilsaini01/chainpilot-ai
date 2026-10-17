#!/usr/bin/env bash
# Browser end-to-end tests against a throwaway copy of the whole stack:
# start it, load the demo data, create one user per role, run Playwright, remove it.
# Usage (from anywhere; Git Bash on Windows): bash apps/web/e2e/run-e2e.sh [playwright args]
set -euo pipefail

cd "$(dirname "$0")/../../.."
compose() { docker compose --project-name chainpilot-e2e --env-file apps/web/e2e/stack.env "$@"; }

# Always remove the stack, its data and its images, even when a test fails.
trap 'compose down --volumes --rmi local' EXIT

compose up --build --detach --wait --wait-timeout 180
compose run --rm -T api python -m app.cli seed
compose run --rm -T api python -m app.cli load-policies

# Fresh random passwords on every run; they exist only in this shell.
for role in admin manager analyst; do
  password="e2e-$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  export "E2E_${role^^}_PASSWORD=$password"
  CHAINPILOT_NEW_USER_PASSWORD="$password" compose run --rm -T -e CHAINPILOT_NEW_USER_PASSWORD api \
    python -m app.cli create-user --email "e2e-$role@example.com" --full-name "E2E ${role^}" --role "$role"
done

# In a subshell, so the clean-up above still runs from the repository root.
(cd apps/web && E2E_BASE_URL=http://127.0.0.1:8082 npx playwright test "$@")
