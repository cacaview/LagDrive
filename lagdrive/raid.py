"""RAID storage engine — multi-relay striped/mirrored/parity storage.

Orchestrates multiple StorageClient instances to provide:
  RAID 0  — round-robin block striping, no redundancy
  RAID 1  — full mirroring to all relays
  RAID 5  — striping with distributed XOR parity (>= 3 relays)
  RAID 10 — mirrored pairs with striping (>= 4 relays, even count)

Data blocks live in a single central RingBuffer for reads.
Write distribution sends blocks to physical relay clients.
"""

from __future__ import annotations

import threading
from time import monotonic

from .models import PerRelayRTT, RAIDMode, RelayHealth, StorageBlock
from .storage import RingBuffer, StorageClient


class RAIDStorageClient:
    """Multi-relay storage client implementing RAID 0/1/5/10.

    Owns one central RingBuffer (for local reads) and one StorageClient
    per relay (for network send/receive).  Blocks are written to the
    central ring, then distributed to physical clients according to the
    RAID level.

    Threading: ``write`` is called from the Monitor thread or CLI;
    ``read`` is called from the same thread.  The central ring is NOT
    locked internally — the caller (Monitor) already holds its own lock
    when calling storage methods.  Physical clients manage their own
    receiver threads independently.
    """

    def __init__(
        self,
        relays: list[tuple[str, int]],
        mode: RAIDMode,
        ring: RingBuffer | None = None,
        block_size: int = 65536,
    ) -> None:
        if len(relays) < 2:
            raise ValueError("RAID requires at least 2 relays")
        self.relays = relays
        self.mode = mode
        self._block_size = block_size
        self._ring = ring or RingBuffer(max_bytes=1_000_000, block_size=block_size)
        self._lock = threading.Lock()
        self._clients: list[StorageClient] = []
        self._connected = False
        self._relay_health: list[RelayHealth] = [
            RelayHealth(address=(h, p)) for h, p in self.relays
        ]
        self._relay_rtt: list[PerRelayRTT] = [PerRelayRTT() for _ in self.relays]
        self._validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        n = len(self.relays)
        if self.mode == RAIDMode.RAID5 and n < 3:
            raise ValueError("RAID 5 requires at least 3 relays")
        if self.mode == RAIDMode.RAID10:
            if n < 4:
                raise ValueError("RAID 10 requires at least 4 relays")
            if n % 2 != 0:
                raise ValueError("RAID 10 requires an even number of relays")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to all relays."""
        if self._connected:
            return
        try:
            for host, port in self.relays:
                client = StorageClient(host, port, ring=self._ring)
                client.connect()
                self._clients.append(client)
        except OSError:
            self.disconnect()
            raise
        self._connected = True

    def disconnect(self) -> None:
        """Disconnect all relay clients."""
        self._connected = False
        for client in self._clients:
            try:
                client.disconnect()
            except Exception:
                pass
        self._clients.clear()

    def _check_relays(self) -> None:
        """Poll each client's connected status and update relay health."""
        for i, client in enumerate(self._clients):
            was_alive = self._relay_health[i].alive
            is_alive = client.connected
            self._relay_health[i].alive = is_alive
            if is_alive:
                self._relay_health[i].consecutive_failures = 0
                self._relay_health[i].last_success_time = monotonic()
            else:
                if was_alive:
                    self._relay_health[i].last_failure_time = monotonic()
                self._relay_health[i].consecutive_failures += 1

    def _collect_relay_rtt(self) -> None:
        """Extract per-relay RTT from recently confirmed blocks.

        A block's ack_time - send_time is the ECHO round-trip to the relay
        that confirmed it.
        """
        for block in self._ring._blocks.values():
            if (block.confirmed and block.ack_time > 0
                    and block.send_time > 0 and block.relay_targets):
                rtt = (block.ack_time - block.send_time) * 1000  # ms
                if rtt > 0:
                    for relay_idx in block.relay_targets:
                        if 0 <= relay_idx < len(self._relay_rtt):
                            self._relay_rtt[relay_idx].update(rtt)

    @property
    def _relay_rtt_map(self) -> dict[int, float] | None:
        """Map relay_index -> avg_rtt_ms for per-block TTL."""
        if not any(rt.avg > 0 for rt in self._relay_rtt):
            return None  # fallback to global RTT
        return {i: rt.avg for i, rt in enumerate(self._relay_rtt)}

    # ------------------------------------------------------------------
    # Write — RAID-mode-aware block distribution
    # ------------------------------------------------------------------

    def write(self, data: bytes) -> dict:
        """Store data in the central ring buffer and distribute to relays.

        Returns write summary dict (same shape as StorageClient.write).
        """
        with self._lock:
            n_relays = len(self._clients)
            blocks = self._ring.write(data)

            if self.mode == RAIDMode.RAID5 and blocks:
                stripe_size = n_relays - 1
                parity_blocks = self._build_raid5_parity(
                    blocks, stripe_size, self._ring,
                )
                all_blocks = blocks + parity_blocks
            else:
                all_blocks = blocks

            sent = 0
            for block in all_blocks:
                targets = self._get_targets(block, n_relays)
                block.relay_targets = targets
                block_sent = False
                for idx in targets:
                    if 0 <= idx < len(self._clients):
                        if not self._relay_health[idx].alive:
                            self._relay_health[idx].total_sends += 1
                            continue
                        success = self._clients[idx].send_block(block)
                        self._relay_health[idx].total_sends += 1
                        if success:
                            sent += 1
                            block_sent = True
                        else:
                            self._relay_health[idx].total_failures += 1
                            self._relay_health[idx].alive = False
                if not block_sent and block.is_parity < 0:
                    block.send_failed = True

            stats = self._ring.stats

        return {
            "blocks_written": len(blocks),
            "bytes_written": sum(b.size for b in blocks),
            "capacity_remaining": stats["capacity_bytes"] - stats["used_bytes"],
            "raid_mode": self.mode.value,
            "physical_sends": sent,
        }

    def _build_raid5_parity(
        self,
        data_blocks: list[StorageBlock],
        stripe_size: int,
        ring: RingBuffer | None = None,
    ) -> list[StorageBlock]:
        """Create XOR parity blocks for RAID 5 stripes and store in ring.

        Parity is distributed: stripe i's parity sits on relay
        ``i % n_relays``.  ``is_parity`` encodes both stripe and relay:
        ``is_parity = stripe_idx * n_relays + parity_relay``.

        Args:
            ring: The RingBuffer to store parity blocks into.  When
                  called from ``write()`` this is ``self._ring``; in
                  unit-tests it can be a different ring so that
                  ``_next_id`` stays consistent.
        """
        if ring is None:
            ring = self._ring
        parity_blocks: list[StorageBlock] = []
        n_relays = stripe_size + 1
        now = monotonic()

        for stripe_start in range(0, len(data_blocks), stripe_size):
            stripe = data_blocks[stripe_start : stripe_start + stripe_size]
            max_size = max(b.size for b in stripe)
            parity = bytearray(max_size)
            for blk in stripe:
                padded = blk.data + b'\x00' * (max_size - blk.size)
                for i in range(max_size):
                    parity[i] ^= padded[i]

            stripe_idx = stripe[0].block_id // stripe_size
            parity_relay = stripe_idx % n_relays

            parity_block = StorageBlock(
                block_id=ring._next_id,
                data=bytes(parity),
                offset=stripe[0].offset,
                send_time=now,
                is_parity=stripe_idx * n_relays + parity_relay,
            )
            ring._blocks[parity_block.block_id] = parity_block
            ring._next_id += 1
            parity_blocks.append(parity_block)

        return parity_blocks

    # ------------------------------------------------------------------
    # Target selection per block
    # ------------------------------------------------------------------

    def _get_targets(self, block: StorageBlock, n_relays: int) -> list[int]:
        """Return relay indices that should receive this block.

        Data blocks are dispatched per RAID mode; parity blocks go
        only to their owning relay (stored in ``is_parity``).
        """
        # Parity blocks — go to the relay indicated by is_parity % n_relays
        if block.is_parity >= 0:
            return [block.is_parity % n_relays]

        # Data blocks — dispatched by RAID mode
        if self.mode == RAIDMode.RAID0:
            return [block.block_id % n_relays]

        if self.mode == RAIDMode.RAID1:
            return list(range(n_relays))

        if self.mode == RAIDMode.RAID5:
            # Data blocks go to relay (block_id % (n-1)), skipping the
            # parity relay for this stripe.
            stripe_size = n_relays - 1
            stripe_idx = block.block_id // max(1, stripe_size)
            parity_relay = stripe_idx % n_relays
            data_relay = block.block_id % stripe_size
            if data_relay >= parity_relay:
                data_relay += 1
            return [data_relay]

        if self.mode == RAIDMode.RAID10:
            pair_idx = block.block_id % (n_relays // 2)
            r0, r1 = pair_idx * 2, pair_idx * 2 + 1
            return [r0, r1]

        return [0]

    # ------------------------------------------------------------------
    # Read — with RAID5 degraded-mode reconstruction
    # ------------------------------------------------------------------

    def read(self, offset: int, length: int) -> bytes:
        """Read data from the central ring buffer, with RAID5 reconstruction."""
        result = bytearray(length)
        end = offset + length
        n_relays = len(self.relays)
        stripe_size = n_relays - 1 if n_relays > 0 else 1

        for block in self._ring._blocks.values():
            if block.is_parity >= 0:
                continue

            block_start = block.offset
            block_end = block_start + block.size

            if block_start >= end or block_end <= offset:
                continue

            if block.expired or block.send_failed:
                if self.mode == RAIDMode.RAID5:
                    reconstructed = self._reconstruct_block(
                        block.block_id, block.size, stripe_size,
                    )
                    if reconstructed:
                        overlap_start = max(offset, block_start)
                        overlap_end = min(end, block_end)
                        src_start = overlap_start - block_start
                        dst_start = overlap_start - offset
                        length_here = overlap_end - overlap_start
                        result[dst_start:dst_start + length_here] = (
                            reconstructed[src_start:src_start + length_here]
                        )
                continue

            overlap_start = max(offset, block_start)
            overlap_end = min(end, block_end)
            src_start = overlap_start - block_start
            dst_start = overlap_start - offset
            length_here = overlap_end - overlap_start
            result[dst_start:dst_start + length_here] = (
                block.data[src_start:src_start + length_here]
            )

        return bytes(result)

    def _has_parity(self, block_id: int) -> bool:
        """Check if a parity block exists for the stripe containing block_id."""
        n_relays = len(self.relays)
        if n_relays < 2:
            return False
        stripe_size = n_relays - 1
        stripe_idx = block_id // stripe_size
        expected = stripe_idx * n_relays + stripe_idx % n_relays
        return any(
            b.is_parity == expected
            for b in self._ring._blocks.values()
            if b.is_parity >= 0
        )

    def _reconstruct_block(
        self,
        missing_block_id: int,
        missing_size: int,
        stripe_size: int | None = None,
    ) -> bytes | None:
        """XOR-reconstruct a missing data block from parity + survivors.

        Groups blocks by stripe (using block_id // stripe_size).
        XORs the parity block's data with surviving data blocks to recover
        the missing block.
        """
        if stripe_size is None:
            n_relays = len(self.relays)
            stripe_size = n_relays - 1 if n_relays > 0 else 1

        stripe_idx = missing_block_id // stripe_size
        stripe_start = stripe_idx * stripe_size
        n_relays = stripe_size + 1
        parity_relay = stripe_idx % n_relays

        parity_block = None
        surviving_blocks = []
        missing_block = None
        expected_parity = stripe_idx * n_relays + parity_relay

        for block in self._ring._blocks.values():
            if block.is_parity >= 0:
                if block.is_parity == expected_parity:
                    parity_block = block
                continue

            bid = block.block_id
            if bid < stripe_start or bid >= stripe_start + stripe_size:
                continue

            if bid == missing_block_id:
                missing_block = block
            elif not block.expired and not block.send_failed:
                surviving_blocks.append(block)

        if parity_block is None:
            return None

        parity_data = parity_block.data
        if parity_block.expired and parity_block._original_data:
            parity_data = parity_block._original_data
        if not parity_data:
            return None

        result = bytearray(parity_data)
        for blk in surviving_blocks:
            blk_data = blk.data
            if blk.expired and blk._original_data:
                blk_data = blk._original_data
            for i in range(min(len(blk_data), len(result))):
                result[i] ^= blk_data[i]

        return bytes(result[:missing_size])

    # ------------------------------------------------------------------
    # Metrics — called by Monitor each tick
    # ------------------------------------------------------------------

    def update_metrics(self, rtt_ms: float, capacity_bytes: float) -> None:
        """Update TTL and capacity across all physical ring buffers.

        Args:
            rtt_ms: Average RTT from the probe engine.
            capacity_bytes: BDP-scaled capacity (already RAID-adjusted).
        """
        with self._lock:
            self._check_relays()
            self._collect_relay_rtt()
            if capacity_bytes > 0:
                self._ring.update_capacity(int(capacity_bytes))
            if rtt_ms > 0:
                self._ring.expire_stale_blocks(rtt_ms, self._relay_rtt_map)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        with self._lock:
            s = self._ring.stats
            alive_count = sum(1 for h in self._relay_health if h.alive)
            dead_relays = [
                {"index": i, "address": f"{h.address[0]}:{h.address[1]}", "failures": h.consecutive_failures}
                for i, h in enumerate(self._relay_health) if not h.alive
            ]
            health_list = [
                {
                    "address": f"{h.address[0]}:{h.address[1]}",
                    "alive": h.alive,
                    "failures": h.consecutive_failures,
                    "total_sends": h.total_sends,
                }
                for h in self._relay_health
            ]
            rtt_list = [
                {"avg_ms": round(rt.avg, 1), "current_ms": round(rt.current, 1)}
                for rt in self._relay_rtt
            ]
        s["relay_connected"] = alive_count > 0
        s["relay_alive_count"] = alive_count
        s["relay_dead_count"] = len(self._relay_health) - alive_count
        s["raid_mode"] = self.mode.value
        s["relay_count"] = len(self._clients)
        s["degraded"] = alive_count < len(self._relay_health)
        s["dead_relays"] = dead_relays
        s["relay_health"] = health_list
        s["relay_rtt"] = rtt_list
        return s
