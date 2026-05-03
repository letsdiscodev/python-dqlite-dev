# Test cluster

3-node dqlite cluster used by the integration tests of the four
sibling Python packages (`python-dqlite-wire`, `python-dqlite-client`,
`python-dqlite-dbapi`, `sqlalchemy-dqlite`).

## Quick start

```bash
docker compose up -d
./scripts/wait-for-cluster.sh
```

Stop and reset:

```bash
docker compose down -v   # -v wipes the per-node data volumes
```

## Cluster shape

| Service | Container hostname | Host-mapped port | Raft node id | Role      |
|---------|--------------------|------------------|--------------|-----------|
| node1   | node1              | 19001 → 9001     | 1            | Bootstrap |
| node2   | node2              | 19002 → 9002     | 2            | Voter     |
| node3   | node3              | 19003 → 9003     | 3            | Voter     |

Container-internal ports stay at 9001-9003 so node-to-node Raft
traffic uses the canonical addresses; host-side mapping uses the
19001-19003 range to avoid colliding with anything else listening on
9001-9003.

## The image

The compose file pins `letsdiscodev/dqlite:0.1.0-patched-null`. That
image is built from this directory's `Dockerfile`, which:

1. Clones `canonical/dqlite` at v1.18.5,
2. Applies `patches/0001-preserve-sqlite-null-type-for-null-values.patch`
   (the local fix for canonical/dqlite#882 — without it, NULL cells
   in `BOOLEAN` / `DATETIME` columns are indistinguishable from
   `False` / `""` on the wire),
3. Builds the dqlite + raft + go-dqlite-demo binaries,
4. Drops them into a slim runtime image alongside the
   `scripts/init-node.sh` and `scripts/healthcheck.sh` entry-points.

To rebuild from source instead of pulling:

```bash
docker compose build
docker compose up -d
```

When canonical/dqlite#882 lands upstream and a release ships, bump
the `DQLITE_VERSION` build-arg in the `Dockerfile` and drop the
patch.

## Health checks

Each node has a shallow TCP-listen healthcheck so compose's
`depends_on: condition: service_healthy` correctly sequences the
follower nodes behind the bootstrap node:

```bash
docker compose ps
```

Healthy means "TCP port is listening". For "node has joined the
cluster and is serving Raft writes", connect a client and call
`ClusterClient.find_leader()` (or use the project's
`scripts/wait-for-cluster.sh` for a basic readiness loop).

## Environment variables

The Python packages' integration tests honour two environment
variables for cluster discovery:

| Variable                      | Default                                                | What it controls                                                  |
|-------------------------------|--------------------------------------------------------|-------------------------------------------------------------------|
| `DQLITE_TEST_CLUSTER`         | `localhost:9001`                                       | Single-node bootstrap address (some tests want exactly one entry) |
| `DQLITE_TEST_CLUSTER_NODES`   | `localhost:19001,localhost:19002,localhost:19003`      | Full host-mapped node list (most fixtures use this)               |

The `scripts/run-tests.sh` runner sets both to point at this
cluster's host-mapped ports, so simply running the runner from a
checkout of `python-dqlite-dev` with the cluster up is enough.

## Files

- `Dockerfile` — multi-stage image build (canonical/dqlite + patch).
- `docker-compose.yml` — 3-node cluster definition.
- `patches/` — local patches applied to the upstream dqlite source.
- `scripts/init-node.sh` — per-node entrypoint baked into the image.
- `scripts/healthcheck.sh` — container healthcheck baked into the image.
- `scripts/wait-for-cluster.sh` — host-side readiness loop for CI scripts.

## Known limitations

The cluster runs on the docker-compose default bridge network. Nodes
advertise their bind address back to clients as `0.0.0.0:9001` etc.
— the container-internal address — which is **not reachable from the
docker host**. That breaks any client path that follows a
leader-redirect against this cluster from a host-side test runner;
see the test-skip notes in the sibling repos
(`test_query_raw_apis.py`, `test_pool_concurrent_tx_leader_flip.py`,
`test_cluster_admin_methods_live.py`). Lifting that limitation is
on the roadmap for this repo.
