"""Pytest fixtures wrapping :class:`TestClusterControl`.

Imported by consumer packages that have already arranged for
``dqlitetestlib`` to be on ``sys.path`` (the conftest.py bootstrap
documented in ``python-dqlite-dev/testlib/README.md``).
"""

from __future__ import annotations

import os

import pytest

from dqlitetestlib.cluster_control import TestClusterControl


def _addresses_from_env() -> list[str]:
    """Read ``DQLITE_TEST_CLUSTER_NODES`` (comma-separated) with the
    canonical 3-node-on-localhost default that matches the
    python-dqlite-dev cluster.
    """
    raw = os.environ.get(
        "DQLITE_TEST_CLUSTER_NODES",
        "localhost:9001,localhost:9002,localhost:9003",
    )
    return [s.strip() for s in raw.split(",") if s.strip()]


@pytest.fixture
def cluster_control() -> TestClusterControl:
    """Yield a :class:`TestClusterControl` bound to the env-configured
    cluster (``DQLITE_TEST_CLUSTER_NODES``).

    Tests that mutate cluster state (leader flip, future kill/restart
    primitives) should restore the cluster's invariants in their own
    teardown — this fixture does not snapshot or revert state.
    """
    return TestClusterControl(_addresses_from_env())
