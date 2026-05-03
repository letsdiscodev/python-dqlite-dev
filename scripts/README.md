# Scripts

Helper scripts that operate across the four sibling packages.

## `run-tests.sh`

Runs ruff, mypy, and pytest across `python-dqlite-wire`,
`python-dqlite-client`, `python-dqlite-dbapi`, and `sqlalchemy-dqlite`,
then runs the SQLAlchemy dialect compliance suite under
`sqlalchemy-dqlite/tests/compliance/`.

### Layout assumed

The script discovers sibling packages by walking one directory up
from this repo:

```
<workspace>/
├── python-dqlite-dev/        # this repo
│   ├── scripts/run-tests.sh
│   └── cluster/docker-compose.yml
├── python-dqlite-wire/
├── python-dqlite-client/
├── python-dqlite-dbapi/
└── sqlalchemy-dqlite/
```

If a sibling is missing, that package is reported as `SKIP` and the
runner continues.

### Modes

```bash
./scripts/run-tests.sh              # default: bring cluster up, lint + unit + integration
./scripts/run-tests.sh --unit       # unit tests only — skips cluster + integration
./scripts/run-tests.sh --no-lint    # skip ruff + mypy
./scripts/run-tests.sh --no-cluster # tests against an already-running cluster
```

The runner exits non-zero if any per-package step fails and prints a
failure list at the end.

### Cluster env vars

The integration suites read `DQLITE_TEST_CLUSTER` (single bootstrap
address, default `localhost:9001`) and `DQLITE_TEST_CLUSTER_NODES`
(comma-separated node list, default `localhost:9001,localhost:9002,
localhost:9003`). The cluster runs on these canonical ports, so
the defaults match the cluster's bind addresses — running pytest
by hand needs no env-var overrides. The runner exports both anyway
to keep the contract obvious.
