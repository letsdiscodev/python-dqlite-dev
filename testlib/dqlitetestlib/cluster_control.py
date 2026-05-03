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
from collections.abc import Sequence
from dataclasses import dataclass

from dqliteclient.cluster import ClusterClient
from dqliteclient.node_store import MemoryNodeStore
from dqlitewire import NodeRole
from dqlitewire.messages.responses import NodeInfo


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
        candidates = [
            n for n in nodes if n.role == NodeRole.VOTER and n.node_id != node_id
        ]
        if not candidates:
            raise RuntimeError(
                f"no voter other than {node_id} available; cluster has {nodes!r}"
            )
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

    # --- Internals ---

    def _client(self) -> ClusterClient:
        store = MemoryNodeStore(self._addresses)
        return ClusterClient(store, timeout=self._timeout)
