"""Shared test utilities for the python-dqlite stack.

This package is NOT pip-installed. Consumer packages reach it via a
``sys.path`` insertion in their ``tests/conftest.py`` that points at
``<workspace>/python-dqlite-dev/testlib``. See the python-dqlite-dev
``testlib/README.md`` for the bootstrap snippet.

Public surface:

- :class:`TestClusterControl` — drives the test cluster
  deterministically (transfer leadership, observe convergence)
  using the admin methods in ``python-dqlite-client``.
- :func:`cluster_control` — pytest fixture wrapping
  :class:`TestClusterControl` against the env-configured cluster.
"""

from dqlitetestlib.cluster_control import TestClusterControl
from dqlitetestlib.fixtures import cluster_control

__all__ = ["TestClusterControl", "cluster_control"]
