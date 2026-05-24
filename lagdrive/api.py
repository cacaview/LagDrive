"""LagDrive programmatic API — for debugging, testing, and embedding.

Usage:
    from lagdrive.api import LagDriveAPI

    api = LagDriveAPI(target="1.1.1.1")
    api.start()
    ...
    snapshot = api.snapshot()
    api.stop()

    # One-shot probes (no background thread)
    rtt = LagDriveAPI.probe_rtt("1.1.1.1")
    tp  = LagDriveAPI.probe_throughput()
"""

from __future__ import annotations

import socket
import time
from dataclasses import asdict

from .models import NetworkMetrics
from .monitor import Monitor, MonitorConfig
from .quotes import select_quote


class LagDriveAPI:
    """Programmatic interface to LagDrive's probe engine.

    All state is accessible via snapshot() for easy JSON serialization.
    One-shot class methods run probes without starting a background thread.
    """

    def __init__(
        self,
        target: str = "1.1.1.1",
        port: int = 80,
        probe_interval: float = 2.0,
        throughput_interval: float = 30.0,
        relay_host: str = "127.0.0.1",
        relay_port: int = 9527,
        storage_enabled: bool = False,
    ) -> None:
        self._config = MonitorConfig(
            target=target,
            port=port,
            probe_interval=probe_interval,
            throughput_interval=throughput_interval,
            relay_host=relay_host,
            relay_port=relay_port,
            storage_enabled=storage_enabled,
        )
        self._monitor = Monitor(self._config)

    # --- Lifecycle ---

    def start(self) -> None:
        """Start the background probe engine."""
        self._monitor.start()

    def stop(self) -> None:
        """Stop the background probe engine."""
        self._monitor.stop()

    @property
    def running(self) -> bool:
        return self._monitor._running

    # --- State access ---

    def snapshot(self) -> dict:
        """Return current monitoring state as a dict.

        Thread-safe — can be called from any thread.
        Suitable for JSON serialization / REST endpoints.
        """
        return self._monitor.get_snapshot()

    def metrics(self) -> NetworkMetrics:
        """Return the raw NetworkMetrics object (read-only intent)."""
        return self._monitor.metrics

    def grid(self) -> list[list[str]]:
        """Return the grid as a 2D list of state strings."""
        return [
            [cell.state.value for cell in row]
            for row in self._monitor.grid
        ]

    def quote(self) -> str:
        """Get the latest sarcastic quote."""
        return self._monitor._last_quote or ""

    # --- Storage operations ---

    def write(self, data: bytes) -> dict:
        """Store data in the network via Echo Relay.

        Returns:
            {"blocks_written": int, "bytes_written": int, "capacity_remaining": int}
        """
        if self._monitor._storage is None:
            return {"blocks_written": 0, "bytes_written": 0, "error": "storage not enabled"}
        return self._monitor._storage.write(data)

    def read(self, offset: int, length: int) -> bytes:
        """Read stored data from the network ring buffer."""
        if self._monitor._storage is None:
            return b''
        return self._monitor._storage.read(offset, length)

    def storage_info(self) -> dict | None:
        """Current storage status. Returns None if storage not enabled."""
        if self._monitor._storage is None:
            return None
        return self._monitor._storage.stats

    def clear_storage(self) -> dict:
        """Clear all stored blocks."""
        if self._monitor._storage is None:
            return {"cleared": False, "error": "storage not enabled"}
        with self._monitor._storage._lock:
            stats = self._monitor._storage._ring.stats
            self._monitor._storage._ring.clear()
        return {"cleared": True, "blocks_cleared": stats["total_blocks"]}

    def enable_storage(self, relay_host: str = "127.0.0.1", relay_port: int = 9527) -> dict:
        """Connect to relay and enable storage at runtime."""
        if self._monitor._storage is not None:
            return {"enabled": False, "error": "already enabled"}
        from .storage import StorageClient, RingBuffer
        ring = RingBuffer(max_bytes=1_000_000, block_size=self._config.block_size)
        client = StorageClient(relay_host, relay_port, ring=ring)
        try:
            client.connect()
            self._monitor._storage = client
            return {"enabled": True, "relay": f"{relay_host}:{relay_port}"}
        except Exception as e:
            return {"enabled": False, "error": str(e)}

    def disable_storage(self) -> dict:
        """Disconnect relay and disable storage."""
        if self._monitor._storage is None:
            return {"disabled": False, "error": "not enabled"}
        self._monitor._storage.disconnect()
        self._monitor._storage = None
        return {"disabled": True}

    # --- One-shot probes (no background thread) ---

    @staticmethod
    def probe_rtt(
        target: str = "1.1.1.1",
        port: int = 80,
        count: int = 5,
        timeout: float = 3.0,
    ) -> dict:
        """Run a one-shot RTT probe. Returns results dict.

        Returns:
            {
                "target": str,
                "samples": [float],   # individual RTTs in ms
                "avg_ms": float,
                "min_ms": float,
                "max_ms": float,
                "success": int,
                "fail": int,
            }
        """
        samples: list[float] = []
        fail = 0
        for _ in range(count):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                t0 = time.perf_counter()
                sock.connect((target, port))
                elapsed = (time.perf_counter() - t0) * 1000
                sock.close()
                samples.append(round(elapsed, 2))
            except (socket.timeout, OSError):
                fail += 1
        return {
            "target": target,
            "samples": samples,
            "avg_ms": round(sum(samples) / len(samples), 2) if samples else 0.0,
            "min_ms": round(min(samples), 2) if samples else 0.0,
            "max_ms": round(max(samples), 2) if samples else 0.0,
            "success": len(samples),
            "fail": fail,
        }

    @staticmethod
    def probe_throughput(test_size: int = 10_000_000) -> dict:
        """Run a one-shot HTTP throughput test. Returns results dict.

        Returns:
            {
                "bytes_downloaded": int,
                "elapsed_s": float,
                "mbps": float,
            }
        """
        import urllib.request

        url = f"https://speed.cloudflare.com/__down?bytes={test_size}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LagDrive/1.0"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            elapsed = time.perf_counter() - t0
            mbps = (len(data) * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
            return {
                "bytes_downloaded": len(data),
                "elapsed_s": round(elapsed, 3),
                "mbps": round(mbps, 2),
            }
        except Exception as e:
            return {
                "bytes_downloaded": 0,
                "elapsed_s": 0.0,
                "mbps": 0.0,
                "error": str(e),
            }

    @staticmethod
    def compute_bdp(rtt_ms: float, throughput_mbps: float) -> dict:
        """Compute BDP (virtual capacity) from raw measurements.

        Returns:
            {
                "rtt_ms": float,
                "throughput_mbps": float,
                "capacity_bytes": float,
                "capacity_human": str,
            }
        """
        if rtt_ms <= 0 or throughput_mbps <= 0:
            return {
                "rtt_ms": rtt_ms,
                "throughput_mbps": throughput_mbps,
                "capacity_bytes": 0.0,
                "capacity_human": "0 B",
            }
        rtt_s = rtt_ms / 1000.0
        bps = throughput_mbps * 1_000_000
        cap = bps * rtt_s / 8.0
        return {
            "rtt_ms": rtt_ms,
            "throughput_mbps": throughput_mbps,
            "capacity_bytes": round(cap, 2),
            "capacity_human": _human_bytes(cap),
        }

    @staticmethod
    def get_quote(
        rtt_avg: float = 0,
        loss_rate: float = 0,
        total_downloaded: int = 0,
        throughput_avg: float = 0,
        capacity: float = 0,
    ) -> str:
        """Get a sarcastic quote for given network conditions."""
        return select_quote(rtt_avg, loss_rate, total_downloaded, throughput_avg, capacity)


def _human_bytes(value: float) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    v = float(value)
    while v >= 1024 and idx < len(units) - 1:
        v /= 1024
        idx += 1
    return f"{v:.2f} {units[idx]}"
