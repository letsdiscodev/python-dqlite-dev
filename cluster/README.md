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

| Service | Bind / advertised address | Role      |
|---------|---------------------------|-----------|
| node1   | 127.0.0.1:9001            | Bootstrap |
| node2   | 127.0.0.1:9002            | Voter     |
| node3   | 127.0.0.1:9003            | Voter     |

The cluster runs in `network_mode: host` so the address each node
advertises (`127.0.0.1:9001` etc.) is reachable from peer
containers and from a host-side test runner alike. No
container-to-host port mapping is involved — `localhost:9001`
inside any container is the same loopback the host sees.

Ports 9001-9003 are dqlite's canonical defaults and match the
sibling packages' integration-test defaults (`DQLITE_TEST_CLUSTER`
defaults to `localhost:9001`), so no env-var overrides are needed
for the standard run.

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

| Variable                      | Default                                              | What it controls                                                  |
|-------------------------------|------------------------------------------------------|-------------------------------------------------------------------|
| `DQLITE_TEST_CLUSTER`         | `localhost:9001`                                     | Single-node bootstrap address (some tests want exactly one entry) |
| `DQLITE_TEST_CLUSTER_NODES`   | `localhost:9001,localhost:9002,localhost:9003`       | Full node list (most fixtures use this)                           |

These defaults match the cluster's bind addresses, so simply running
the test runner (or pytest directly) with the cluster up is enough —
no exports needed.

## Files

- `Dockerfile` — multi-stage image build (canonical/dqlite + patch).
- `docker-compose.yml` — 3-node cluster definition.
- `patches/` — local patches applied to the upstream dqlite source.
- `scripts/init-node.sh` — per-node entrypoint baked into the image.
- `scripts/healthcheck.sh` — container healthcheck baked into the image.
- `scripts/wait-for-cluster.sh` — host-side readiness loop for CI scripts.

## Architecture notes

- **Host networking, loopback advertisement**: nodes advertise
  `127.0.0.1:9001` etc. — reachable from peer containers
  (`localhost` is the same loopback inside any host-network
  container) and from a host-side test runner. The previous
  bridge-mode setup advertised `0.0.0.0:9001`, which clients
  correctly reject as the unspecified IP literal — that is what
  blocked the leader-flip test family from running.
- **Distinct ports per node**: required because all three
  containers share the host's loopback. node1=9001, node2=9002,
  node3=9003 — same port range as the canonical dqlite defaults.
- **Auto-generated Raft node ids**: the `dqlite-demo` binary
  generates node ids on first boot; they are NOT the `NODE_ID`
  env var (which the in-repo `init-node.sh` only uses for the data
  subdirectory). Tests that need to address a node by id should
  read the live id from `ClusterClient.cluster_info()`.
