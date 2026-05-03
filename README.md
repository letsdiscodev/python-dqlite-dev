# python-dqlite-dev

Development-environment glue for the four-package Python dqlite stack:

- [`python-dqlite-wire`](https://github.com/letsdiscodev/python-dqlite-wire)
  — wire-protocol codec (encode + decode every dqlite request/response type).
- [`python-dqlite-client`](https://github.com/letsdiscodev/python-dqlite-client)
  — async client (leader discovery, connection management, admin ops).
- [`python-dqlite-dbapi`](https://github.com/letsdiscodev/python-dqlite-dbapi)
  — PEP 249 (DB-API 2.0) sync + async surface.
- [`sqlalchemy-dqlite`](https://github.com/letsdiscodev/sqlalchemy-dqlite)
  — SQLAlchemy 2.0 dialect (sync `dqlite://` + async `dqlite+aio://`).

This repo contains the dev-environment pieces shared across all four:
the test cluster (Docker), the cross-package test runner, and (in a
follow-up) shared test fixtures and a fault-injection helper. None of
this ships as a published package — it is a development-only repo
that contributors clone alongside the four production packages.

## Layout

```
<workspace>/                       # any directory; the four packages
│                                  # must be siblings of this repo
├── python-dqlite-dev/             # this repo
│   ├── cluster/                   # 3-node test cluster
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   ├── patches/
│   │   ├── scripts/
│   │   └── README.md
│   ├── scripts/
│   │   ├── run-tests.sh           # runs lint + tests across all 4 packages
│   │   └── README.md
│   └── testlib/                   # placeholder; TestClusterControl lands here
├── python-dqlite-wire/
├── python-dqlite-client/
├── python-dqlite-dbapi/
└── sqlalchemy-dqlite/
```

The four production packages reference each other via
`[tool.uv.sources]` path-links (`python-dqlite-dbapi` depends on
sibling `../python-dqlite-client`, etc.), so cloning all five into a
single workspace lets `uv sync` pick up local edits without
publishing or installing.

## First-time setup

1. Install [uv](https://docs.astral.sh/uv/) and Docker.
2. Clone all five repos into one workspace directory:

   ```bash
   mkdir dqlite-workspace && cd dqlite-workspace
   for repo in python-dqlite-dev python-dqlite-wire \
               python-dqlite-client python-dqlite-dbapi \
               sqlalchemy-dqlite; do
       git clone "https://github.com/letsdiscodev/${repo}.git"
   done
   ```

3. Sync each package's dev environment:

   ```bash
   for pkg in python-dqlite-wire python-dqlite-client \
              python-dqlite-dbapi sqlalchemy-dqlite; do
       (cd "$pkg" && uv sync --extra dev)
   done
   ```

## Running the test suite

Bring up the test cluster and run all packages' tests:

```bash
cd python-dqlite-dev
./scripts/run-tests.sh
```

That will:

1. Start the 3-node cluster from `cluster/docker-compose.yml`
   (host networking on the canonical 9001-9003 dqlite ports).
2. Wait for each node to listen.
3. Run ruff + mypy + pytest against every sibling package found in
   the parent directory.
4. Run the SQLAlchemy dialect compliance suite under
   `sqlalchemy-dqlite/tests/compliance/`.
5. Report pass / fail per package and exit non-zero on any failure.

Other modes:

```bash
./scripts/run-tests.sh --unit         # unit tests only — no cluster needed
./scripts/run-tests.sh --no-cluster   # tests against an already-running cluster
./scripts/run-tests.sh --no-lint      # skip ruff + mypy
```

To run a single package's tests by hand against this cluster, no
env vars are needed — the integration suites default to
`localhost:9001` (single-node) and `localhost:9001,localhost:9002,
localhost:9003` (full node list) which match the cluster's bind
addresses:

```bash
cd ../python-dqlite-client && uv run pytest tests/integration/
```

See `cluster/README.md` for cluster shape, ports, and the published
image's provenance (canonical/dqlite v1.18.5 + a local patch for
[canonical/dqlite#882](https://github.com/canonical/dqlite/issues/882)).

## Roadmap

- **testlib v0** — `TestClusterControl` (transfer leadership, kill /
  restart nodes) so the leader-flip / pre-ping-recovery tests
  currently skipped across the four packages can run end-to-end.
- **Un-skip the `test_cluster_admin_methods_live` integration test**
  in `python-dqlite-client` (and the analogous skipped tests in
  `sqlalchemy-dqlite`). The address-advertisement issue that
  blocked them is fixed by this repo's host-networking cluster, but
  the skip markers were added under the old setup and need to be
  lifted.

## License

MIT (see `LICENSE`).
