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

# API debug commands
lagdrive --probe-rtt
lagdrive --probe-all
lagdrive --bdp 200 100
lagdrive --snapshot
```

Tests use a custom harness (not pytest) with ANSI-colored output and global pass/fail counters. `--quick` skips network tests. Exit code 0/1.

## Architecture

### Dependency Layers

```
Layer 0 (leaves):   models.py, quotes.py
Layer 1:            monitor.py, relay.py    (imports models)
Layer 2:            storage.py, dashboard.py (imports models, relay)
Layer 3:            api.py                  (imports models, monitor, quotes, storage)
Layer 4 (top):      __init__.py             (imports api, dashboard, monitor)
```

`quotes.select_quote` is lazy-imported inside `monitor._maybe_fire_quote()` to avoid circular imports.

### Threading Model (4 threads in storage mode)

1. **Main thread** — argparse, Rich Live display, user input
2. **Monitor daemon thread** — `asyncio.new_event_loop()` with `ThreadPoolExecutor(max_workers=4)` for blocking socket I/O
3. **Poller daemon thread** (dashboard mode) — polls `api.snapshot()` every 0.5s, pushes to `Dashboard.update()`
4. **Storage receiver thread** (storage mode) — reads ECHO frames from relay, confirms blocks in ring buffer

All Monitor state protected by `threading.Lock`. RingBuffer mutations protected by StorageClient's own lock.

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

**Wire protocol** (`relay.py`): 7-byte header (`!2sBI`: magic b'LD', type, length) + body. Type 0x01=WRITE, 0x02=ECHO. Body: `block_id(u64) + offset(u64) + data`.

**RingBuffer** (`storage.py`): Bounded by BDP capacity. Blocks are 64KB max, 1024 blocks max. FIFO eviction when full. TTL = `max(rtt×2×1.5/1000, 0.5s)`, capped at 30s. Blocks expire without confirmation → data zeroed out.

**StorageClient** (`storage.py`): Connects to relay via TCP. Sends WRITE frames on write(). Background receiver thread reads ECHO frames and confirms blocks. If relay disconnects, blocks expire naturally.

## Pending TODO

- **RAID 0 (Striping) 模式**: 同时向多个目标发包，带宽叠加。需要在 Monitor 中支持多目标配置、并发 stripe 探测、合并带宽计算。PRD 路径: `prd.txt` §6 Phase 2。

## Known Issues

- **Dead dependency**: `psutil` is declared in `pyproject.toml` but never imported.
- **Private member access**: `LagDriveAPI.running` reads `self._monitor._running` directly.
- **`_human_bytes` duplication**: Near-identical formatting in `api.py` and `dashboard.py`, differing only in decimal precision.
