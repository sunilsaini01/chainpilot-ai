#!/usr/bin/env bash
# Imports a data folder (forecasts or delivery-risk scores) into the staging database.
# The folder must already be in the private imports bucket (docs/AWS_RUNBOOK.md).
# A one-off task downloads it through presigned links that expire after an hour
# (so the API's task role needs no S3 permission), then runs the import command.
# Usage: bash infrastructure/scripts/import-from-s3.sh import-forecasts forecasts/m5_lightgbm_weekly_2016-04-24
set -euo pipefail

command_name=$1 # import-forecasts or import-delivery-risk
prefix=${2%/}   # folder inside the imports bucket
scripts=$(cd "$(dirname "$0")" && pwd)
bucket=$(cd "$scripts/../terraform/staging" && "${TERRAFORM:-terraform}" output -raw imports_bucket)

# name url name url ... for every file in the folder
pairs=()
for key in $(MSYS_NO_PATHCONV=1 aws s3api list-objects-v2 --bucket "$bucket" --prefix "$prefix/" \
  --query "Contents[].Key" --output text); do
  pairs+=("${key##*/}" "$(aws s3 presign "s3://$bucket/$key" --expires-in 3600)")
done
[ ${#pairs[@]} -gt 0 ] || { echo "Nothing found under s3://$bucket/$prefix/"; exit 1; }

# Runs inside the container: download the files into /tmp, then the CLI import.
code='
import sys, urllib.request
from pathlib import Path
from app.cli import main
command, folder, pairs = sys.argv[1], Path("/tmp/import") / sys.argv[2], sys.argv[3:]
folder.mkdir(parents=True)
for name, url in zip(pairs[::2], pairs[1::2]):
    urllib.request.urlretrieve(url, folder / name)
    print("downloaded", name, (folder / name).stat().st_size, "bytes")
sys.exit(main([command, str(folder)]))
'
# More memory than the API's 512 MB: the forecast file has about 850,000 rows.
TASK_CPU=${TASK_CPU:-1024} TASK_MEMORY=${TASK_MEMORY:-4096} \
  bash "$scripts/run-task.sh" python -c "$code" "$command_name" "${prefix##*/}" "${pairs[@]}"
