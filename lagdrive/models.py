from dataclasses import dataclass, field
from enum import Enum
from time import monotonic


class CellState(Enum):
    """State of a virtual disk block in the cluster grid."""
    ACTIVE = "active"     # [·] Blue  — data flowing normally
    FREE = "free"         # [ ] Gray  — unused virtual capacity
    ERROR = "error"       # [!] Red   — TCP retransmission / lag spike
    STORED = "stored"     # [S] Green — data stored in network transit


@dataclass
class GridCell:
    """A single cell in the 10x10 cluster grid."""
    state: CellState = CellState.FREE
    transition_time: float = 0.0

    def set_state(self, state: CellState) -> None:
        if self.state != state:
            self.state = state
            self.transition_time = monotonic()


@dataclass
class NetworkMetrics:
    """Real-time network measurement data."""
    rtt_samples: list[float] = field(default_factory=list)
    rtt_current: float = 0.0
    rtt_avg: float = 0.0
    throughput_current: float = 0.0
    throughput_avg: float = 0.0
    total_downloaded: int = 0
    total_uploaded: int = 0
    loss_rate: float = 0.0
    probe_count: int = 0
    fail_count: int = 0
    capacity: float = 0.0
    last_update: float = 0.0

    def update_rtt(self, value: float, max_samples: int = 15) -> None:
        self.rtt_current = value
        self.rtt_samples.append(value)
        if len(self.rtt_samples) > max_samples:
            self.rtt_samples.pop(0)
        self.rtt_avg = sum(self.rtt_samples) / len(self.rtt_samples)
        self.last_update = monotonic()

    def update_throughput(self, value: float, alpha: float = 0.3) -> None:
        self.throughput_current = value
        if self.throughput_avg == 0:
            self.throughput_avg = value
        else:
            self.throughput_avg = alpha * value + (1 - alpha) * self.throughput_avg
        self.last_update = monotonic()

    @property
    def bdp(self) -> float:
        """Bandwidth-Delay Product — the 'capacity' of the network pipe.

        Formula: Capacity(bytes) = Bandwidth(bps) * RTT(s) / 8
        """
        if self.rtt_avg <= 0 or self.throughput_avg <= 0:
            return 0.0
        rtt_seconds = self.rtt_avg / 1000.0
        bandwidth_bps = self.throughput_avg * 1_000_000
        return bandwidth_bps * rtt_seconds / 8.0

    @property
    def data_in_transit(self) -> float:
        """Real-time bytes currently 'on the wire'."""
        if self.rtt_current <= 0 or self.throughput_avg <= 0:
            return 0.0
        rtt_seconds = self.rtt_current / 1000.0
        bandwidth_bps = self.throughput_avg * 1_000_000
        return bandwidth_bps * rtt_seconds / 8.0


@dataclass
class StorageBlock:
    """A block of data in the network ring buffer."""
    block_id: int
    data: bytes
    offset: int
    send_time: float
    confirmed: bool = False
    expired: bool = False
    ack_time: float = 0.0

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class StorageState:
    """Aggregate storage status."""
    used_bytes: int = 0
    capacity_bytes: int = 0
    total_blocks: int = 0
    confirmed_blocks: int = 0
    expired_blocks: int = 0
    lost_bytes: int = 0
    write_count: int = 0
    read_count: int = 0
    relay_connected: bool = False
