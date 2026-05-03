# testlib

Shared test utilities for the four sibling packages
(`python-dqlite-wire`, `python-dqlite-client`, `python-dqlite-dbapi`,
`sqlalchemy-dqlite`). The testlib provides:

- `TestClusterControl` — drives the test cluster deterministically
  (transfer leadership, observe convergence) using
  `ClusterClient.transfer_leadership` from `python-dqlite-client`.
- A `cluster_control` pytest fixture wrapping the above against the
  env-configured cluster.

Not pip-installable — `python-dqlite-dev` is a development-only repo.
Consumer packages reach the testlib by adding it to `sys.path` from
their own `tests/conftest.py`.

## Bootstrap snippet for consumer packages

In each consumer's `tests/conftest.py`:

```python
import sys
from pathlib import Path

# Add python-dqlite-dev's testlib to sys.path so tests can import
# from ``dqlitetestlib``. Sibling-repo path: tests are at
# <pkg>/tests/conftest.py; python-dqlite-dev is at <workspace>/python-dqlite-dev.
_TESTLIB = (
    Path(__file__).resolve().parent.parent.parent
    / "python-dqlite-dev"
    / "testlib"
)
if _TESTLIB.exists() and str(_TESTLIB) not in sys.path:
    sys.path.insert(0, str(_TESTLIB))

# Re-export the cluster_control fixture so tests can request it by
# name without an explicit import.
pytest_plugins = ["dqlitetestlib.fixtures"]
```

Tests then write:

```python
from dqlitetestlib import TestClusterControl

async def test_pool_recovers_after_leader_flip(
    cluster_control: TestClusterControl,
) -> None:
    result = await cluster_control.force_leader_flip()
    assert result.leader_after == result.target.address
    # ... assert the pool re-routes to the new leader ...
```

## Layout

```
testlib/
└── dqlitetestlib/
    ├── __init__.py        # re-exports TestClusterControl + cluster_control
    ├── cluster_control.py # the class itself
    └── fixtures.py        # pytest fixtures
```

## What it does NOT do (yet)

- **No container kill/restart primitives.** The current
  `TestClusterControl` only flips leadership via
  `transfer_leadership` — the graceful step-down path. Tests that
  need to model a hard node failure (kill the leader, observe pool
  invalidation) need a `kill_node` / `start_node` primitive that
  shells out to docker. Coming when a test actually needs it.
- **No state snapshot/restore.** Tests that flip the leader leave
  the cluster with a different leader than they started; subsequent
  tests must tolerate that, or restore via
  `transfer_leadership_to(original_leader_id)` in their own
  teardown.
