"""Drive the dqlite test cluster from tests.

The class here is the only piece of test machinery that knows how
to flip leadership, enumerate cluster nodes, and observe Raft
convergence. It is deliberately thin — it composes
``ClusterClient.find_leader`` / ``cluster_info`` /
``transfer_leadership`` (added in python-dqlite-client on
2026-05-02) into the fault-injection idioms tests actually want
("flip the leader to anyone but the current one and wait for
convergence").

Usage from a test:

.. code-block:: python

    async def test_pool_pre_ping_recovers_after_leader_flip(
        cluster_control: TestClusterControl,
    ) -> None:
        new_leader = await cluster_control.force_leader_flip()
        # ... assert pool re-routes to ``new_leader.address`` ...

Designed for the in-repo cluster (``python-dqlite-dev/cluster``)
but works against any reachable dqlite cluster — the addresses are
read from ``DQLITE_TEST_CLUSTER_NODES`` (or passed explicitly to
the constructor).
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dqliteclient.cluster import ClusterClient
from dqliteclient.node_store import MemoryNodeStore
from dqlitewire import NodeRole
from dqlitewire.messages.responses import NodeInfo

# Spare-node primitive: docker-compose service name + matching data
# volume name + cluster-internal address. Pinned here because the
# ``start_spare_node`` / ``stop_spare_node`` plumbing references all
# three across multiple subprocess calls; a single source of truth
# avoids drift if compose is renamed.
_SPARE_SERVICE: Final[str] = "node4"
_SPARE_VOLUME: Final[str] = "cluster_node4-data"
_SPARE_ADDRESS: Final[str] = "127.0.0.1:9004"

# python-dqlite-dev/testlib/dqlitetestlib/cluster_control.py
#                  ^^^^^^^^/^^^^^^^^^^^^^/^^^^^^^^^^^^^^^^^^
#                  parent  parent      parent  parent
# python-dqlite-dev/cluster/docker-compose.yml
_CLUSTER_COMPOSE_FILE: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent / "cluster" / "docker-compose.yml"
)


@dataclass(frozen=True)
class _ConvergenceResult:
    """Return value for :meth:`TestClusterControl.force_leader_flip` —
    carries both the targeted node and a witness of the flipped state
    so the caller can pin assertions on both."""

    target: NodeInfo
    leader_after: str


class TestClusterControl:
    """Programmatic cluster control for tests.

    Wraps a :class:`dqliteclient.cluster.ClusterClient` over the
    configured node addresses. Each method opens a fresh one-shot
    admin connection (``ClusterClient`` does that itself); no
    long-lived state lives on this instance, so a fixture can yield
    a single instance per test without lifecycle gymnastics.

    Args:
        addresses: cluster bootstrap addresses (any reachable
            entry — leader discovery follows from there).
        timeout: per-call socket timeout, propagated to the
            underlying :class:`ClusterClient`.
        convergence_timeout: how long :meth:`force_leader_flip`
            polls for the new leader to be observable; should be
            comfortably longer than Raft's election-timeout
            (typically 1 s on a healthy LAN cluster).
        convergence_poll_interval: gap between polls inside
            :meth:`force_leader_flip` and
            :meth:`wait_for_leader_change`.
    """

    def __init__(
        self,
        addresses: Sequence[str],
        *,
        timeout: float = 5.0,
        convergence_timeout: float = 10.0,
        convergence_poll_interval: float = 0.2,
    ) -> None:
        self._addresses = list(addresses)
        self._timeout = timeout
        self._convergence_timeout = convergence_timeout
        self._convergence_poll_interval = convergence_poll_interval

    # --- Read-only helpers ---

    async def find_leader(self) -> str:
        """Return the current leader's advertised address.

        Wraps ``ClusterClient.find_leader``; same failure modes
        (raises ``ClusterError`` if no leader is reachable).
        """
        return await self._client().find_leader()

    async def cluster_info(self) -> list[NodeInfo]:
        """Return the cluster's node list (id, address, role).

        Wraps ``ClusterClient.cluster_info``; queries the current
        leader, returning Raft's view of the configuration.
        """
        return await self._client().cluster_info()

    async def current_leader_node(self) -> NodeInfo:
        """Return the :class:`NodeInfo` for the current leader.

        Convenience: combines :meth:`find_leader` and
        :meth:`cluster_info` so callers can match by node id (which
        ``transfer_leadership`` accepts) rather than address.
        """
        leader_addr = await self.find_leader()
        nodes = await self.cluster_info()
        for n in nodes:
            if n.address == leader_addr:
                return n
        raise RuntimeError(
            f"current leader address {leader_addr!r} not in cluster_info node "
            f"list — Raft view is inconsistent with the leader response. "
            f"Cluster: {nodes!r}"
        )

    async def pick_voter_other_than(self, node_id: int) -> NodeInfo:
        """Return a voter whose ``node_id`` differs from the argument.

        The default :meth:`force_leader_flip` strategy: pick any
        non-current voter as the transfer target. Callers that want
        a specific target should call ``transfer_leadership`` on the
        underlying :class:`ClusterClient` directly instead.
        """
        nodes = await self.cluster_info()
        candidates = [n for n in nodes if n.role == NodeRole.VOTER and n.node_id != node_id]
        if not candidates:
            raise RuntimeError(f"no voter other than {node_id} available; cluster has {nodes!r}")
        return candidates[0]

    # --- Mutating operations ---

    async def transfer_leadership_to(self, target_node_id: int) -> None:
        """Wrap :meth:`ClusterClient.transfer_leadership`.

        Returns once the server has acknowledged the transfer
        request — election convergence is asynchronous and observed
        separately via :meth:`wait_for_leader_change`.
        """
        await self._client().transfer_leadership(target_node_id)

    async def wait_for_leader_change(
        self,
        previous_leader: str,
        *,
        timeout: float | None = None,
    ) -> str:
        """Poll until ``find_leader`` reports an address different
        from ``previous_leader``, or raise ``TimeoutError``.

        Useful when a test triggered a flip indirectly (e.g. by
        killing the leader's container) and wants to assert
        convergence happened.
        """
        deadline = asyncio.get_event_loop().time() + (
            timeout if timeout is not None else self._convergence_timeout
        )
        last_seen: str | None = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                last_seen = await self.find_leader()
            except Exception:
                # Mid-flip the cluster may briefly have no leader; keep
                # polling within the deadline.
                await asyncio.sleep(self._convergence_poll_interval)
                continue
            if last_seen != previous_leader:
                return last_seen
            await asyncio.sleep(self._convergence_poll_interval)
        raise TimeoutError(
            f"leader did not change from {previous_leader!r} within "
            f"{self._convergence_timeout}s; last seen: {last_seen!r}"
        )

    async def force_leader_flip(self) -> _ConvergenceResult:
        """Pick a non-current voter, transfer leadership to it, and
        block until the new leader is observable.

        Returns the targeted :class:`NodeInfo` plus the address
        ``find_leader`` reported once convergence completed (which
        should equal ``target.address`` — caller can assert this).

        Raises ``TimeoutError`` if the cluster does not converge
        within ``convergence_timeout``.
        """
        current = await self.current_leader_node()
        target = await self.pick_voter_other_than(current.node_id)
        await self.transfer_leadership_to(target.node_id)
        leader_after = await self.wait_for_leader_change(current.address)
        return _ConvergenceResult(target=target, leader_after=leader_after)

    # --- Spare-node primitive (docker-driven) ---

    async def start_spare_node(self) -> NodeInfo:
        """Start the docker-compose ``spare`` profile's ``node4``
        and wait for it to auto-join the cluster as a Spare.

        ``dqlite-demo`` self-joins via the ``--join`` flag baked
        into ``init-node.sh``: the node sends an ``Add`` request
        to the bootstrap address as soon as it starts. So this
        method does not call :meth:`add_node` — instead it polls
        :meth:`cluster_info` until a 4th node appears, then
        returns its :class:`NodeInfo`. Tests that want to exercise
        the explicit ``add_node`` API should use the unit/protocol
        tests (this method is for live fault-injection scenarios
        that need a real running 4th node — e.g. promoting a
        Spare to Voter via ``assign_role``).

        Wipes any prior ``node4`` data volume before starting so
        a residual data directory from a previous run cannot
        confuse Raft about which cluster the node belongs to.

        Returns the new :class:`NodeInfo` so the caller has the
        Raft-assigned ``node_id`` for follow-up
        :meth:`assign_role` / :meth:`remove_node` calls.

        Raises:
            RuntimeError: if docker-compose fails to bring node4 up.
            TimeoutError: if node4 does not appear in
                ``cluster_info`` within
                ``convergence_timeout``.
        """
        # Snapshot the cluster's current node ids so we can pick
        # the auto-joining node out of the post-start state.
        starting = await self.cluster_info()
        starting_ids = {n.node_id for n in starting}

        # Belt-and-braces cleanup of any prior state. ``stop_spare_node``
        # already does this on shutdown, but a previous test that
        # crashed mid-flight could have left a stale container or
        # volume behind. ``check=False`` so the no-op cases (nothing
        # to remove) don't raise.
        _run_compose("rm", "-fsv", _SPARE_SERVICE, check=False)
        _run_docker("volume", "rm", "-f", _SPARE_VOLUME, check=False)

        _run_compose("--profile", "spare", "up", "-d", _SPARE_SERVICE)

        # Poll for node4 to surface in cluster_info. Auto-join
        # latency is typically sub-second on a healthy LAN cluster
        # but we give a generous deadline to tolerate slow CI hosts.
        deadline = asyncio.get_event_loop().time() + self._convergence_timeout * 2
        last_seen_count = len(starting)
        while asyncio.get_event_loop().time() < deadline:
            try:
                nodes = await self.cluster_info()
            except Exception:
                # Mid-config-change cluster_info can briefly fail;
                # keep polling within the deadline.
                await asyncio.sleep(self._convergence_poll_interval)
                continue
            new_nodes = [n for n in nodes if n.node_id not in starting_ids]
            last_seen_count = len(nodes)
            if new_nodes:
                # First appearance wins. There should only ever be one
                # new node since we wiped the volume above.
                return new_nodes[0]
            await asyncio.sleep(self._convergence_poll_interval)
        raise TimeoutError(
            f"spare node did not auto-join within "
            f"{self._convergence_timeout * 2}s; cluster has "
            f"{last_seen_count} nodes (expected {len(starting) + 1})"
        )

    async def stop_spare_node(self, node_id: int) -> None:
        """Tear down a spare node previously started by
        :meth:`start_spare_node`.

        Cleanup ordering is load-bearing for cluster integrity:

        1. ``cluster.remove_node(node_id)`` — removes the node from
           the Raft config so the cluster stops trying to replicate
           to it. Without this, stopping the container would leave
           an unreachable peer in the config; the cluster would log
           replication failures (still correct, just noisy) and
           subsequent runs that try to re-add the same id would
           collide.
        2. ``docker compose stop / rm`` — terminates and removes the
           container.
        3. ``docker volume rm`` — wipes the data directory so a
           fresh ``start_spare_node`` cannot pick up a stale Raft
           state from this run.

        Each step is best-effort: if step 1 fails (e.g. cluster
        already lost track of the node), we still proceed with
        steps 2 and 3 so the docker-side state is always cleaned
        up.
        """
        with contextlib.suppress(Exception):
            await self.remove_node(node_id)
        _run_compose("stop", _SPARE_SERVICE, check=False)
        _run_compose("rm", "-fsv", _SPARE_SERVICE, check=False)
        _run_docker("volume", "rm", "-f", _SPARE_VOLUME, check=False)

    @contextlib.asynccontextmanager
    async def spare_node(self) -> AsyncIterator[NodeInfo]:
        """Async context manager wrapping
        :meth:`start_spare_node` + :meth:`stop_spare_node` so
        tests don't have to manage the cleanup explicitly.

        .. code-block:: python

            async with cluster_control.spare_node() as spare:
                await cluster_control.assign_role(spare.node_id, NodeRole.VOTER)
                # ... live test against the now-Voter spare node ...
        """
        node = await self.start_spare_node()
        try:
            yield node
        finally:
            await self.stop_spare_node(node.node_id)

    # --- Convenience wrappers around ClusterClient mutators ---

    async def remove_node(self, node_id: int) -> None:
        """Forwarder so test fixtures can do membership cleanup
        (in particular :meth:`spare_node`'s teardown) without
        constructing their own :class:`ClusterClient`."""
        await self._client().remove_node(node_id)

    async def assign_role(self, node_id: int, role: NodeRole) -> None:
        """Forwarder for :meth:`ClusterClient.assign_role`. Same
        rationale as :meth:`remove_node` above."""
        await self._client().assign_role(node_id, role)

    async def wait_for_role(
        self,
        node_id: int,
        role: NodeRole,
        *,
        timeout: float | None = None,
    ) -> None:
        """Block until ``cluster_info()`` reports ``node_id`` with
        the requested ``role``, or raise ``TimeoutError``.

        Raft propagates a role change asynchronously — the leader
        accepts the ``Assign`` request, then replicates the new
        config; followers (including the target node) observe the
        change after the next AppendEntries round. This poll is
        the test-side wait for that convergence.
        """
        deadline = asyncio.get_event_loop().time() + (
            timeout if timeout is not None else self._convergence_timeout
        )
        observed: NodeRole | None = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                nodes = await self.cluster_info()
            except Exception:
                await asyncio.sleep(self._convergence_poll_interval)
                continue
            for n in nodes:
                if n.node_id == node_id:
                    observed = n.role
                    if n.role == role:
                        return
            await asyncio.sleep(self._convergence_poll_interval)
        raise TimeoutError(
            f"node {node_id} did not converge to role {role} within "
            f"{self._convergence_timeout}s; last observed role: {observed}"
        )

    # --- Internals ---

    def _client(self) -> ClusterClient:
        store = MemoryNodeStore(self._addresses)
        return ClusterClient(store, timeout=self._timeout)


def _run_compose(*args: str, check: bool = True) -> None:
    """Run ``docker compose -f <repo-cluster-yml> <args>`` from a
    deterministic working directory so volume names are stable
    (compose derives the project name from the directory the file
    lives in unless ``-p`` is set).

    ``check=True`` raises ``RuntimeError`` on non-zero exit so the
    test fixture surfaces a clear error rather than silently
    proceeding with a half-set-up cluster.
    """
    cmd = [
        "docker",
        "compose",
        "-f",
        str(_CLUSTER_COMPOSE_FILE),
        *args,
    ]
    result = subprocess.run(  # noqa: S603 — args are not user-controlled
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker compose {args!r} failed (exit {result.returncode}):\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )


def _run_docker(*args: str, check: bool = True) -> None:
    """Run ``docker <args>`` (for ``volume rm`` etc. where
    ``docker compose`` does not provide a direct command).
    """
    cmd = ["docker", *args]
    result = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker {args!r} failed (exit {result.returncode}):\nstderr: {result.stderr}"
        )
