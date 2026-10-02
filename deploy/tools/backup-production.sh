#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
compose() {
    docker compose --env-file deploy/.env.production -f deploy/compose.production.yml "$@"
}
python3 deploy/check-production.py
compose stop api
trap 'compose start api' EXIT
compose --profile tools run --rm backup
