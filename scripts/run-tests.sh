#!/bin/bash
# run-tests.sh — usage: ./run-tests.sh [test-tags]
# sh mnt/extra-addons/pulse_digest/scripts/run-tests.sh 
# sh mnt/extra-addons/pulse_digest/scripts/run-tests.sh /pulse_digest

set -eux
TAGS="${1:-/pulse_digest}"
DB_ARGS="--db_host db --db_user odoo --db_password odoo"

odoo db $DB_ARGS drop pulse_test || true

# odoo -d pulse_test   -i pulse_digest   --test-enable   --test-tags /pulse_digest   --stop-after-init   --max-cron-threads=0   --log-level=test --db_host=db --db_user=odoo --db_password=odoo -p 8068


odoo -d pulse_test -i pulse_digest \
  --test-enable --test-tags "$TAGS" \
  --stop-after-init --max-cron-threads=0 --log-level=test \
  $DB_ARGS -p 8068