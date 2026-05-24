import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .models import CellState, GridCell, NetworkMetrics, RAIDMode


@dataclass
class MonitorConfig:
    """Configuration for the probe engine."""
    target: str = "1.1.1.1"
    port: int = 80
    probe_interval: float = 2.0
    throughput_interval: float = 30.0
    throughput_test_size: int = 10_000_000
    rtt_timeout: float = 2.0
    concurrent_probes: int = 3
    grid_rows: int = 10
    grid_cols: int = 10
    # Storage (single relay — backward compatible)
    relay_host: str = "127.0.0.1"
    relay_port: int = 9527
    storage_enabled: bool = False
    block_size: int = 65536
    # RAID (multi-relay)
    raid_mode: RAIDMode = RAIDMode.NONE
    relays: list[tuple[str, int]] | None = None


class Monitor:
    """TCP probe engine — measures RTT, throughput, and packet loss.

    Runs in a background thread with its own asyncio event loop.
    Publishes state updates via callbacks.
    """

    # Callbacks (optional — CLI uses these; API polls via snapshot)
    on_capacity_update: Callable[[NetworkMetrics], None] | None = None
    on_state_change: Callable[[list[list[GridCell]]], None] | None = None
    on_quote: Callable[[str], None] | None = None

    # --- Lifecycle ---

    def __init__(self, config: MonitorConfig | None = None) -> None:
        self.config = config or MonitorConfig()
        self.metrics = NetworkMetrics()
        self.grid: list[list[GridCell]] = [
            [GridCell() for _ in range(self.config.grid_cols)]
            for _ in range(self.config.grid_rows)
        ]
        self._lock = threading.Lock()
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._last_quote_time = 0.0
        self._quote_interval = 15.0
        # Internal snapshot for API polling
        self._last_quote: str = ""
        # Storage
        self._storage = None

    def start(self) -> None:
        """Start the probe engine in a background thread."""
        if self._running:
            return
        if self.config.storage_enabled:
            if (self.config.raid_mode != RAIDMode.NONE
                    and self.config.relays
                    and len(self.config.relays) >= 2):
                from .raid import RAIDStorageClient
                from .storage import RingBuffer
                ring = RingBuffer(max_bytes=1_000_000, block_size=self.config.block_size)
                self._storage = RAIDStorageClient(
                    relays=self.config.relays,
                    mode=self.config.raid_mode,
                    ring=ring,
                    block_size=self.config.block_size,
                )
                self._storage.connect()
            else:
                from .storage import StorageClient, RingBuffer
                ring = RingBuffer(max_bytes=1_000_000, block_size=self.config.block_size)
                self._storage = StorageClient(
                    self.config.relay_host, self.config.relay_port, ring=ring,
                )
                self._storage.connect()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the probe engine gracefully."""
        self._running = False
        if self._storage:
            self._storage.disconnect()
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)

    # --- Internal event loop ---

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        finally:
            self._executor.shutdown(wait=False)
            self._loop.close()

    async def _run(self) -> None:
        self._task = asyncio.current_task()
        throughput_counter = 0
        try:
            while self._running:
                with self._lock:
                    self._update_grid()

                await asyncio.gather(
                    self._rtt_tick(),
                    self._throughput_tick(throughput_counter),
                )
                throughput_counter += 1

                with self._lock:
                    self._calculate_capacity()
                    self._storage_tick()
                    self._fire_state_change()
                    self._maybe_fire_quote()

                await asyncio.sleep(self.config.probe_interval)
        except asyncio.CancelledError:
            pass

    # --- RTT measurement ---

    async def _rtt_tick(self) -> None:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(self._executor, self._measure_rtt)
        with self._lock:
            self.metrics.probe_count += 1
            if result is not None:
                self.metrics.update_rtt(result)
                # SYN+ACK packet overhead per probe
                n = self.config.concurrent_probes
                self.metrics.total_uploaded += 60 * n
                self.metrics.total_downloaded += 60 * n
            else:
                self.metrics.fail_count += 1
            if self.metrics.probe_count > 0:
                self.metrics.loss_rate = self.metrics.fail_count / self.metrics.probe_count

    def _measure_rtt(self) -> float | None:
        """TCP connect-time RTT measurement using SYN→SYN-ACK timing."""
        latencies: list[float] = []
        for _ in range(self.config.concurrent_probes):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.config.rtt_timeout)
            try:
                t0 = time.perf_counter()
                sock.connect((self.config.target, self.config.port))
                elapsed_ms = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed_ms)
            except (socket.timeout, OSError):
                pass
            finally:
                sock.close()
        if not latencies:
            return None
        return sum(latencies) / len(latencies)

    # --- Throughput measurement ---

    async def _throughput_tick(self, counter: int) -> None:
        if counter == 0 or counter % max(1, int(
            self.config.throughput_interval / self.config.probe_interval
        )) != 0:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._measure_throughput)

    def _measure_throughput(self) -> None:
        """HTTP-based throughput test using public endpoints."""
        import urllib.request

        url = (
            "https://speed.cloudflare.com/__down"
            f"?bytes={self.config.throughput_test_size}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LagDrive/1.0"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            elapsed = time.perf_counter() - t0

            bytes_down = len(data)
            if elapsed > 0:
                mbps = (bytes_down * 8) / (elapsed * 1_000_000)
                with self._lock:
                    self.metrics.total_downloaded += bytes_down
                    self.metrics.total_uploaded += 200
                    self.metrics.update_throughput(mbps)
        except (OSError, socket.timeout) as e:
            import sys
            print(f"[LagDrive] throughput probe failed: {e}", file=sys.stderr)

    # --- Capacity calculation ---

    def _calculate_capacity(self) -> None:
        base = self.metrics.bdp
        if self._storage is not None and self.config.relays:
            self.metrics.capacity = self._raid_capacity(base)
        else:
            self.metrics.capacity = base

    def _raid_capacity(self, base_bdp: float) -> float:
        """Scale BDP capacity according to RAID mode."""
        n = len(self.config.relays)
        mode = self.config.raid_mode
        storage = self._storage
        if storage is not None and hasattr(storage, '_relay_health'):
            alive = sum(1 for h in storage._relay_health if h.alive)
        else:
            alive = n
        if mode == RAIDMode.RAID0:
            return base_bdp * alive
        if mode == RAIDMode.RAID1:
            return base_bdp
        if mode == RAIDMode.RAID5:
            return base_bdp * max(alive - 1, 0)
        if mode == RAIDMode.RAID10:
            return base_bdp * (alive // 2)
        return base_bdp

    # --- Storage tick ---

    def _storage_tick(self) -> None:
        storage = self._storage
        if storage is None:
            return
        storage.update_metrics(self.metrics.rtt_avg, self.metrics.capacity)

    # --- Grid state management ---

    def _update_grid(self) -> None:
        rows, cols = self.config.grid_rows, self.config.grid_cols
        total = rows * cols

        loss = self.metrics.loss_rate
        rtt = self.metrics.rtt_avg

        if rtt <= 0:
            error_count = 0
            active_count = 0
        elif loss > 0.05:
            error_count = min(max(1, int(loss * total)), total)
            active_count = max(0, total - error_count)
        else:
            error_count = 0
            utilization = min(rtt / 1000.0, 1.0)
            active_count = int(utilization * total)

        # Storage utilization → stored cells
        stored_count = 0
        storage = self._storage
        if storage is not None:
            st = storage.stats
            cap = st.get("capacity_bytes", 0)
            used = st.get("used_bytes", 0)
            if cap > 0:
                stored_count = int(min(used / cap, 1.0) * total)
                stored_count = min(stored_count, total - error_count)

        # Priority: error > stored > active > free
        idx = 0
        for r in range(rows):
            for c in range(cols):
                cell = self.grid[r][c]
                if idx < error_count:
                    cell.set_state(CellState.ERROR)
                elif idx < error_count + stored_count:
                    cell.set_state(CellState.STORED)
                elif idx < error_count + stored_count + active_count:
                    cell.set_state(CellState.ACTIVE)
                else:
                    cell.set_state(CellState.FREE)
                idx += 1

    # --- Event dispatch ---

    def _fire_state_change(self) -> None:
        if self.on_state_change:
            self.on_state_change(self.grid)

    def get_snapshot(self) -> dict:
        """Return a copy of the current monitoring state (thread-safe)."""
        with self._lock:
            storage = self._storage
            snap = {
                "running": self._running,
                "rtt_current": self.metrics.rtt_current,
                "rtt_avg": self.metrics.rtt_avg,
                "throughput_current": self.metrics.throughput_current,
                "throughput_avg": self.metrics.throughput_avg,
                "loss_rate": self.metrics.loss_rate,
                "capacity": self.metrics.capacity,
                "data_in_transit": self.metrics.data_in_transit,
                "total_downloaded": self.metrics.total_downloaded,
                "total_uploaded": self.metrics.total_uploaded,
                "probe_count": self.metrics.probe_count,
                "fail_count": self.metrics.fail_count,
                "quote": self._last_quote,
                "storage": storage.stats if storage else None,
                "grid": [[cell.state.value for cell in row] for row in self.grid],
            }
            return snap

    def _maybe_fire_quote(self) -> None:
        now = time.monotonic()
        if now - self._last_quote_time < self._quote_interval:
            return
        self._last_quote_time = now

        storage_event = None
        storage = self._storage
        if storage is not None and hasattr(storage, '_relay_health'):
            alive = sum(1 for h in storage._relay_health if h.alive)
            total = len(storage._relay_health)
            if 0 < alive < total:
                storage_event = "raid_degraded"

        from .quotes import select_quote
        quote = select_quote(
            self.metrics.rtt_avg,
            self.metrics.loss_rate,
            self.metrics.total_downloaded,
            self.metrics.throughput_avg,
            self.metrics.capacity,
            storage_event=storage_event,
        )
        self._last_quote = quote
        if self.on_quote:
            self.on_quote(quote)
