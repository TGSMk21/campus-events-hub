#!/usr/bin/env bash
# Local PostgreSQL for development without Docker or a system install.
# Uses binaries from PATH if present, otherwise the `pgserver` pip package (pip install pgserver).
#   scripts/devdb.sh start | stop | status | psql
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="$PWD/.pgdata"
PORT="${PGPORT:-5432}"

if command -v pg_ctl >/dev/null 2>&1; then
  BIN="$(dirname "$(command -v pg_ctl)")"
else
  BIN="$(python -c 'import os, pgserver; print(os.path.join(os.path.dirname(pgserver.__file__), "pginstall", "bin"))')"
fi

case "${1:-start}" in
  start)
    if [ ! -f "$DATA/PG_VERSION" ]; then
      "$BIN/initdb" -D "$DATA" -U "$USER" --auth=trust --encoding=UTF8 --locale=C >/dev/null
      echo "Initialised cluster in $DATA"
    fi
    "$BIN/pg_ctl" -D "$DATA" -l "$DATA/server.log" -o "-p $PORT -k /tmp" -w status >/dev/null 2>&1 \
      || "$BIN/pg_ctl" -D "$DATA" -l "$DATA/server.log" -o "-p $PORT -k /tmp -c listen_addresses=localhost" -w start
    for db in campus_hub campus_hub_test; do
      "$BIN/psql" -h localhost -p "$PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || "$BIN/createdb" -h localhost -p "$PORT" "$db"
    done
    echo "PostgreSQL running on localhost:$PORT (databases: campus_hub, campus_hub_test)"
    ;;
  stop)   "$BIN/pg_ctl" -D "$DATA" -w stop ;;
  status) "$BIN/pg_ctl" -D "$DATA" status ;;
  psql)   shift; "$BIN/psql" -h localhost -p "$PORT" -d campus_hub "$@" ;;
  *) echo "usage: $0 start|stop|status|psql"; exit 1 ;;
esac
