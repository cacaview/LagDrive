# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LagDrive is a Python CLI tool that turns network latency into real virtual disk storage using BDP (Bandwidth-Delay Product): `Capacity(bytes) = Bandwidth(bps) × RTT(s) / 8`. Data is sent to an Echo Relay server and "lives" in the network pipe while in transit. The relay echoes data back; data that doesn't return before TTL expires is lost. Volatility is a feature.

## Commands

```bash
pip install -e .

# Tests
python test_api.py              # Full suite (includes TCP probes)
python test_api.py --quick      # Skip network tests
python test_api.py --network    # Include throughput test (~30s)

# Dashboard (default mode)
lagdrive
lagdrive -t 8.8.8.8
lagdrive --storage              # Enable storage mode (requires running relay)

# Echo Relay server
lagdrive --relay
lagdrive --relay --relay-port 9527

# Storage operations
lagdrive --store "hello world"
lagdrive --read 0 11
lagdrive --storage-info

# RAID multi-relay storage
lagdrive --raid-mode raid0 --relays 127.0.0.1:9527 127.0.0.1:9528 --store "hello RAID"
lagdrive --raid-mode raid5 --relays 127.0.0.1:9527 127.0.0.1:9528 127.0.0.1:9529 --store "hello RAID5"

# API debug commands
lagdrive --probe-rtt
lagdrive --probe-throughput
lagdrive --probe-all
lagdrive --bdp 200 100
lagdrive --snapshot
```

Tests use a custom harness (not pytest) with ANSI-colored output and global pass/fail counters. `--quick` skips network tests. Exit code 0/1.

## Development Rules

- **API-first**: Every feature must have a corresponding method in `LagDriveAPI` (`api.py`) before it can be wired into the CLI or dashboard. This ensures all functionality is independently testable and debuggable via `from lagdrive.api import LagDriveAPI`. When adding a new feature, implement the `api.py` method first, add tests in `test_api.py`, then wire it into `__init__.py` / dashboard.

## Architecture

### Dependency Layers

```
Layer 0 (leaves):   models.py, quotes.py, relay.py  (no internal imports)
Layer 1:            monitor.py                       (imports models)
Layer 2:            storage.py, dashboard.py         (imports models; storage also imports relay, dashboard imports quotes)
Layer 3:            raid.py                          (imports models, storage)
Layer 4:            api.py                           (imports models, monitor, quotes; storage/raid lazy-imported in methods)
Layer 5 (top):      __init__.py                      (imports api, dashboard, monitor)
```

`quotes.select_quote` is lazy-imported inside `monitor._maybe_fire_quote()` to avoid circular imports.
`raid.RAIDStorageClient` is lazy-imported inside `Monitor.start()` to avoid circular imports.

### Threading Model (4–4+N threads in storage mode)

1. **Main thread** — argparse, Rich Live display, user input
2. **Monitor daemon thread** — `asyncio.new_event_loop()` with `ThreadPoolExecutor(max_workers=4)` for blocking socket I/O
3. **Poller daemon thread** (dashboard mode) — polls `api.snapshot()` every 0.5s, pushes to `Dashboard.update()`
4. **Storage receiver thread(s)** — 1 per relay connection; reads ECHO frames and confirms blocks in shared RingBuffer

All Monitor state protected by `threading.Lock`. RingBuffer mutations protected by StorageClient/RAIDStorageClient's own lock.

### Key Data Flow

- **RTT**: 3 TCP connect-time probes per tick → sliding window (15 samples) → `rtt_avg`
- **Throughput**: HTTP download from Cloudflare every 30s → EMA (α=0.3) → `throughput_avg`
- **BDP**: `throughput_avg × 1M × (rtt_avg / 1000) / 8` → `capacity` bytes
- **Grid**: 10×10 cells — `STORED` (green [S]) for stored data, `ACTIVE` (blue [·]) for flowing data, `ERROR` (red [!]) for retransmissions, `FREE` (gray [ ]) for unused space
- **Quotes**: Priority routing: storage events > loss > RTT extremes > traffic > throughput > capacity > neutral

### Storage Architecture

```
Client (lagdrive)                    Echo Relay (--relay)
┌──────────────┐                    ┌──────────────┐
│ StorageClient│── WRITE frame ───>│              │
│  ┌─────────┐ │<── ECHO frame ───│  echoes back  │
│  │RingBuffer│ │                  │              │
│  └─────────┘ │                    └──────────────┘
│  Monitor     │ ← RTT/BDP updates TTL and capacity
└──────────────┘
```

### RAID Architecture (raid.py)

```
Client (lagdrive)           Relay 0     Relay 1     Relay 2
┌──────────────────┐       ┌─────┐     ┌─────┐     ┌─────┐
│ RAIDStorageClient│       │     │     │     │     │     │
│  ┌─────────────┐ │       │     │     │     │     │     │
│  │ RingBuffer  │ │       │     │     │     │     │     │
│  │ (central)   │ │       │     │     │     │     │     │
│  └─────────────┘ │       │     │     │     │     │     │
│  StorageClient ×N├── ──> │ Echo│     │ Echo│     │ Echo│
│  RAID 0/1/5/10   │<── ──│     │     │     │     │     │
└──────────────────┘       └─────┘     └─────┘     └─────┘
```

RAID modes: RAID 0 (round-robin striping), RAID 1 (mirroring to all), RAID 5 (XOR parity distributed across relays), RAID 10 (mirrored pairs + striping). Capacity scaling in `Monitor._raid_capacity()`. Parity blocks are stored in the shared RingBuffer with `is_parity >= 0` (value = owning relay index) and excluded from `read()`.

**RAID 5 failure detection**: `_check_relays()` polls `client.connected` each tick. Per-relay health tracked in `RelayHealth` dataclass. Dead relays are skipped on write; blocks get `send_failed=True` if all targets fail. Degraded mode triggers `raid_degraded` quotes.

**RAID 5 reconstruction**: `_reconstruct_block(block_id, size, stripe_size)` XORs the parity block with surviving data blocks in the same stripe (`block_id // stripe_size`). `read()` calls this automatically for expired/failed blocks in RAID 5 mode. `_original_data` is preserved by `expire_stale_blocks()` before zeroing. Parity blocks encode both stripe index and relay index: `is_parity = stripe_idx * n_relays + parity_relay`, enabling correct matching when stripes cycle through relays more than once.

**Per-relay RTT**: `_collect_relay_rtt()` harvests ECHO round-trip times (`ack_time - send_time`) from confirmed blocks. Per-relay RTT used for block TTL when available, falling back to global RTT.

**Dashboard RAID switching**: `[M]` key in TUI opens mode switch dialog. `LagDriveAPI.switch_raid_mode()` disconnects and reconnects with new configuration.

**Wire protocol** (`relay.py`): 7-byte header (`!2sBI`: magic b'LD', type, length) + body. Type 0x01=WRITE, 0x02=ECHO. Body: `block_id(u64) + offset(u64) + data`.

**RingBuffer** (`storage.py`): Bounded by BDP capacity. Blocks are 64KB max, 1024 blocks max. FIFO eviction when full. TTL = `max(rtt×2×1.5/1000, 0.5s)`, capped at 30s. Blocks expire without confirmation → data zeroed out.

**StorageClient** (`storage.py`): Connects to relay via TCP. Sends WRITE frames on write(). `send_block()` for RAID block distribution. Background receiver thread reads ECHO frames and confirms blocks. If relay disconnects, blocks expire naturally.

## Known Issues

- **Private member access**: `LagDriveAPI.running` reads `self._monitor._running` directly.
- **`_human_bytes` duplication**: Near-identical byte formatting in `api.py` (`_human_bytes` → `str`, `:.2f`) and `dashboard.py` (`_format_bytes` → `tuple[str, str]`, `:.1f`).
