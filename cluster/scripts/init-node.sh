#!/bin/bash
#
# Per-node entrypoint for the dqlite test cluster.
#
# Reads the node-shape from environment variables passed by
# docker-compose.yml:
#
#   NODE_ID    Numeric Raft node id (1, 2, 3 in the default cluster).
#   PORT       Container-internal Raft / database port (9001-9003).
#   API_PORT   Container-internal HTTP API port (8001-8003).
#   BOOTSTRAP  "true" only on the seed node; absent on followers.
#   JOIN       host:port of any existing node, used by followers to
#              join the cluster. Ignored when BOOTSTRAP=true.
#
# Data persists in /data/node${NODE_ID}, mounted from the
# node${N}-data volume in compose so an ``up -d`` after ``down``
# resumes the same Raft log.

set -e

DATA_DIR="/data/node${NODE_ID}"
mkdir -p "$DATA_DIR"

# Bind on all container interfaces so node-to-node traffic and the
# host-mapped ports both work. The address dqlite advertises to its
# Raft peers comes from this binding — peers reach each other via
# the docker-compose service hostnames (node1, node2, node3).
BIND_ADDRESS="0.0.0.0:${PORT}"

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
