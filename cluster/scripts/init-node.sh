#!/bin/bash
#
# Per-node entrypoint for the dqlite test cluster.
#
# Reads the node-shape from environment variables passed by
# docker-compose.yml:
#
#   NODE_ID       Numeric Raft node id (1, 2, 3 in the default cluster).
#   PORT          Container-listening Raft / database port (19001-19003 on
#                 host network).
#   API_PORT      Container-listening HTTP API port (18001-18003).
#   BIND_ADDRESS  Address dqlite-demo binds to AND advertises to peers
#                 (e.g. ``127.0.0.1:19001``). Required.
#   BOOTSTRAP     "true" only on the seed node; absent on followers.
#   JOIN          Bind-address of any existing node, used by followers
#                 to join the cluster. Ignored when BOOTSTRAP=true.
#
# Data persists in /data/node${NODE_ID}, mounted from the
# node${N}-data volume in compose so an ``up -d`` after ``down``
# resumes the same Raft log. Wipe with ``docker compose down -v``.

set -e

DATA_DIR="/data/node${NODE_ID}"
mkdir -p "$DATA_DIR"

if [ -z "$BIND_ADDRESS" ]; then
    echo "ERROR: BIND_ADDRESS not set" >&2
    exit 1
fi

if [ "$BOOTSTRAP" = "true" ]; then
    echo "Starting bootstrap node (id=${NODE_ID}) at ${BIND_ADDRESS}"
    exec /app/dqlite-demo \
        --dir "$DATA_DIR" \
        --db "$BIND_ADDRESS" \
        --api "0.0.0.0:${API_PORT}"
else
    echo "Joining cluster via ${JOIN} (node id=${NODE_ID} at ${BIND_ADDRESS})"
    # Followers race the bootstrap node's leader election. A short
    # sleep avoids hammering the seed node before it is ready to
    # accept the join request; ``depends_on: condition: service_healthy``
    # in compose covers most of this but the demo binary's join path
    # has its own retry-on-connect-refused that this just shortens.
    sleep 2
    exec /app/dqlite-demo \
        --dir "$DATA_DIR" \
        --db "$BIND_ADDRESS" \
        --api "0.0.0.0:${API_PORT}" \
        --join "$JOIN"
fi
