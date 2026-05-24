"""Network storage engine — ring buffer + relay client.

The RingBuffer stores data blocks that are "in flight" on the network.
Blocks expire after their TTL (derived from RTT). When the relay echoes
a block back, it's confirmed. When a block expires without confirmation,
its data is zeroed out — this is the volatility feature.

The StorageClient connects the RingBuffer to the Echo Relay, managing
the TCP connection and a receiver thread that processes ECHO frames.
"""

import socket
import threading
import time
from time import monotonic

from .models import StorageBlock
from .relay import LagDriveProtocol, TYPE_ECHO, TYPE_WRITE


class RingBuffer:
    """Bounded ring buffer for network-stored data blocks.

    Blocks are written sequentially with increasing block_ids.
    When capacity is exceeded, oldest blocks (lowest block_ids) are evicted.
    """

    def __init__(self, max_bytes: int = 1_000_000,
                 max_blocks: int = 1024,
                 block_size: int = 65536) -> None:
        self.max_bytes = max_bytes
        self.max_blocks = max_blocks
        self.block_size = block_size
        self._blocks: dict[int, StorageBlock] = {}
        self._next_id = 0
        self._write_offset = 0
        self._write_count = 0
        self._read_count = 0
        self._lost_bytes = 0

    def write(self, data: bytes) -> list[StorageBlock]:
        """Split data into blocks and store in the ring buffer.

        Returns list of blocks that need to be sent to the relay.
        """
        if not data:
            return []

        now = monotonic()
        blocks_to_send: list[StorageBlock] = []

        for i in range(0, len(data), self.block_size):
            chunk = data[i:i + self.block_size]
            offset = self._write_offset
            block_id = self._next_id

            block = StorageBlock(
                block_id=block_id,
                data=chunk,
                offset=offset,
                send_time=now,
            )

            self._evict_for_space(len(chunk))

            self._blocks[block_id] = block
            self._next_id += 1
            self._write_offset += len(chunk)
            self._write_count += 1
            blocks_to_send.append(block)

        return blocks_to_send

    def read(self, offset: int, length: int) -> bytes:
        """Read data from the ring buffer at the given offset.

        Returns actual data for live blocks, zero bytes for expired/missing ranges.
        """
        self._read_count += 1
        result = bytearray(length)
        end = offset + length

        for block in self._blocks.values():
            if block.expired:
                continue
            block_start = block.offset
            block_end = block_start + block.size
            # Check overlap
            if block_start < end and block_end > offset:
                overlap_start = max(offset, block_start)
                overlap_end = min(end, block_end)
                src_start = overlap_start - block_start
                dst_start = overlap_start - offset
                src_end = src_start + (overlap_end - overlap_start)
                result[dst_start:dst_start + (overlap_end - overlap_start)] = block.data[src_start:src_end]

        return bytes(result)

    def confirm_block(self, block_id: int) -> bool:
        """Mark a block as confirmed (echo received). Returns False if expired/missing."""
        block = self._blocks.get(block_id)
        if block is None or block.expired:
            return False
        if not block.confirmed:
            block.confirmed = True
            block.ack_time = monotonic()
        return True

    def expire_stale_blocks(self, current_rtt_ms: float) -> int:
        """Check and expire blocks that exceeded their TTL.

        TTL = max(rtt_ms * 2 * 1.5 / 1000, 0.5), capped at 30s.
        Returns count of newly expired blocks.
        """
        if current_rtt_ms <= 0:
            return 0

        ttl = max(current_rtt_ms * 2.0 * 1.5 / 1000.0, 0.5)
        ttl = min(ttl, 30.0)
        now = monotonic()
        expired = 0

        for block in self._blocks.values():
            if not block.confirmed and not block.expired:
                if now - block.send_time > ttl:
                    block.expired = True
                    self._lost_bytes += block.size
                    block.data = b'\x00' * block.size
                    expired += 1

        return expired

    def update_capacity(self, new_max_bytes: int) -> None:
        """Update buffer capacity. Evict oldest blocks if over new limit."""
        self.max_bytes = max(new_max_bytes, 0)
        self._evict_oldest_to_fit()

    def _evict_for_space(self, needed: int) -> None:
        """Evict oldest blocks until there's room for `needed` bytes."""
        while self._used_bytes() + needed > self.max_bytes and self._blocks:
            self._evict_oldest()
        while len(self._blocks) >= self.max_blocks and self._blocks:
            self._evict_oldest()

    def _evict_oldest_to_fit(self) -> None:
        """Evict oldest blocks until within capacity."""
        while self._used_bytes() > self.max_bytes and self._blocks:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        """Remove the oldest (lowest block_id) block."""
        if not self._blocks:
            return
        oldest_id = min(self._blocks)
        block = self._blocks.pop(oldest_id)
        if not block.confirmed:
            self._lost_bytes += block.size

    def _used_bytes(self) -> int:
        return sum(b.size for b in self._blocks.values())

    @property
    def stats(self) -> dict:
        total = len(self._blocks)
        confirmed = sum(1 for b in self._blocks.values() if b.confirmed)
        expired = sum(1 for b in self._blocks.values() if b.expired)
        return {
            "used_bytes": self._used_bytes(),
            "capacity_bytes": self.max_bytes,
            "total_blocks": total,
            "confirmed_blocks": confirmed,
            "expired_blocks": expired,
            "lost_bytes": self._lost_bytes,
            "write_count": self._write_count,
            "read_count": self._read_count,
        }

    def clear(self) -> None:
        """Remove all blocks."""
        self._blocks.clear()
        self._next_id = 0
        self._write_offset = 0


class StorageClient:
    """Connects the RingBuffer to the Echo Relay.

    Manages TCP connection, sends WRITE frames, receives ECHO frames
    in a background thread, and confirms blocks in the ring buffer.
    """

    def __init__(self, relay_host: str = "127.0.0.1",
                 relay_port: int = 9527,
                 ring: RingBuffer | None = None) -> None:
        self._host = relay_host
        self._port = relay_port
        self._ring = ring or RingBuffer()
        self._conn: socket.socket | None = None
        self._lock = threading.Lock()
        self._recv_thread: threading.Thread | None = None
        self._connected = False

    def connect(self) -> None:
        """Connect to relay and start receiver thread."""
        if self._connected:
            return
        self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._conn.settimeout(5.0)
        self._conn.connect((self._host, self._port))
        self._conn.settimeout(None)
        self._connected = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def disconnect(self) -> None:
        """Disconnect from relay."""
        self._connected = False
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None

    def write(self, data: bytes) -> dict:
        """Store data in the network ring buffer and send to relay.

        Returns write summary dict.
        """
        with self._lock:
            blocks = self._ring.write(data)

        sent = 0
        for block in blocks:
            try:
                frame = LagDriveProtocol.encode_write(block.block_id, block.offset, block.data)
                if self._conn:
                    self._conn.sendall(frame)
                sent += 1
            except OSError:
                break

        stats = self._ring.stats
        return {
            "blocks_written": sent,
            "bytes_written": sum(b.size for b in blocks),
            "capacity_remaining": stats["capacity_bytes"] - stats["used_bytes"],
        }

    def read(self, offset: int, length: int) -> bytes:
        """Read stored data from the local ring buffer."""
        with self._lock:
            return self._ring.read(offset, length)

    def update_metrics(self, rtt_ms: float, capacity_bytes: float) -> None:
        """Called by Monitor to update TTL base and buffer capacity."""
        with self._lock:
            if capacity_bytes > 0:
                self._ring.update_capacity(int(capacity_bytes))
            if rtt_ms > 0:
                self._ring.expire_stale_blocks(rtt_ms)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict:
        with self._lock:
            s = self._ring.stats
        s["relay_connected"] = self._connected
        return s

    def _recv_loop(self) -> None:
        """Background thread: read ECHO frames and confirm blocks."""
        try:
            while self._connected and self._conn:
                result = LagDriveProtocol.decode_frame(self._conn)
                if result is None:
                    break
                frame_type, body = result
                if frame_type != TYPE_ECHO:
                    continue
                decoded = LagDriveProtocol.decode_block_body(body)
                if decoded is None:
                    continue
                block_id, offset, data = decoded
                with self._lock:
                    self._ring.confirm_block(block_id)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self._connected = False
