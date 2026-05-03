# testlib (placeholder)

Reserved for shared test utilities — pytest fixtures and a
`TestClusterControl` helper that drives the test cluster
deterministically (transfer leadership, kill / restart nodes,
partition / unpartition) so the four sibling packages can express
fault-injection tests instead of skipping them.

This directory is intentionally empty in the initial bootstrap. The
testlib lands in a follow-up — it depends on
`ClusterClient.transfer_leadership` (added in `python-dqlite-client`
on 2026-05-02) plus a `python-docker` SDK wrapper for container
control.

When the testlib lands, the four packages will pull it in via
`[tool.uv.sources]` path-link rather than installing it as a
published package — `python-dqlite-dev` is a development-only repo,
not intended for PyPI.
