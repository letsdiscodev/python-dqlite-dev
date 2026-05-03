#!/bin/bash
#
# Container healthcheck for a dqlite node.
#
# Reports healthy when the node is listening on its Raft port. This
# is shallower than "the node has joined the cluster and is serving"
# (which would need an actual dqlite handshake), but it is enough
# for compose's ``depends_on: condition: service_healthy`` to
# correctly sequence followers behind the bootstrap node — TCP-listen
# means dqlite-demo has finished its startup path and is ready to
# accept the join request.

if nc -z localhost "${PORT}" 2>/dev/null; then
    exit 0
else
    exit 1
fi
