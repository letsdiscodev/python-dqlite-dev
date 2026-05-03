#!/bin/bash
#
# Block until every cluster node accepts a TCP connection on its
# host-mapped port. Useful in CI scripts that bring the cluster up
# and want a deterministic "cluster is ready" signal before starting
# tests, instead of relying on per-test connect retry.
#
# Usage: wait-for-cluster.sh [TIMEOUT_SECONDS]   (default 60)
#
# Probes the host-mapped ports defined in docker-compose.yml — 19001,
# 19002, 19003 — not the container-internal 9001-9003.

set -e

TIMEOUT=${1:-60}
HOST_PORTS="9001 9002 9003"

echo "Waiting for dqlite cluster to be ready (timeout: ${TIMEOUT}s)..."

for port in $HOST_PORTS; do
    echo -n "  localhost:${port}... "

    SECONDS=0
    while ! nc -z localhost "$port" 2>/dev/null; do
        if [ "$SECONDS" -ge "$TIMEOUT" ]; then
            echo "TIMEOUT"
            exit 1
        fi
        sleep 1
    done

    echo "OK"
done

echo "Cluster is ready."
