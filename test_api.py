"""LagDrive API 测试脚本

用法:
    python test_api.py             # 运行全部测试
    python test_api.py --quick     # 跳过网络测试
    python test_api.py --network   # 仅网络测试
"""

import json
import sys
import time

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def section(title: str) -> None:
    print(f"\n{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{CYAN}{'=' * 60}{RESET}\n")


def ok(msg: str) -> None:
    print(f"  {GREEN}[PASS]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}[FAIL]{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}→ {msg}{RESET}")


passed = 0
failed = 0


def check(condition: bool, msg: str) -> None:
    global passed, failed
    if condition:
        ok(msg)
        passed += 1
    else:
        fail(msg)
        failed += 1


# ============================================================
# 1. Import & basic structure
# ============================================================
section("1. 模块导入 & 基础结构")

try:
    from lagdrive import __version__
    check(__version__ == "1.2.0", f"版本号 = {__version__}")
except Exception as e:
    check(False, f"导入 lagdrive 失败: {e}")

try:
    from lagdrive.api import LagDriveAPI
    check(True, "LagDriveAPI 导入成功")
except Exception as e:
    check(False, f"LagDriveAPI 导入失败: {e}")

try:
    from lagdrive.models import CellState, GridCell, NetworkMetrics
    check(True, "models 导入成功")
except Exception as e:
    check(False, f"models 导入失败: {e}")

try:
    from lagdrive.monitor import Monitor, MonitorConfig
    check(True, "monitor 导入成功")
except Exception as e:
    check(False, f"monitor 导入失败: {e}")

try:
    from lagdrive.dashboard import Dashboard
    check(True, "dashboard 导入成功")
except Exception as e:
    check(False, f"dashboard 导入失败: {e}")

try:
    from lagdrive.quotes import select_quote
    check(True, "quotes 导入成功")
except Exception as e:
    check(False, f"quotes 导入失败: {e}")

try:
    from lagdrive.raid import RAIDStorageClient
    check(True, "raid 模块导入成功")
except Exception as e:
    check(False, f"raid 模块导入失败: {e}")


# ============================================================
# 2. Models unit tests
# ============================================================
section("2. Models 单元测试")

# CellState
check(CellState.ACTIVE.value == "active", "CellState.ACTIVE = 'active'")
check(CellState.FREE.value == "free", "CellState.FREE = 'free'")
check(CellState.ERROR.value == "error", "CellState.ERROR = 'error'")

# GridCell
cell = GridCell()
check(cell.state == CellState.FREE, "GridCell 默认状态 = FREE")
cell.set_state(CellState.ACTIVE)
check(cell.state == CellState.ACTIVE, "GridCell.set_state(ACTIVE) 生效")
cell.set_state(CellState.ERROR)
check(cell.state == CellState.ERROR, "GridCell.set_state(ERROR) 生效")

# NetworkMetrics — BDP calculation
m = NetworkMetrics()
check(m.bdp == 0.0, "无数据时 BDP = 0")

m.rtt_avg = 100.0      # 100ms
m.throughput_avg = 10.0  # 10 Mbps
bdp = m.bdp
expected_bdp = 10 * 1_000_000 * 0.1 / 8  # = 125000 bytes
check(abs(bdp - expected_bdp) < 1, f"BDP(100ms, 10Mbps) = {bdp:.0f} bytes (期望 ~125000)")

# NetworkMetrics — data in transit
m.rtt_current = 200.0
dit = m.data_in_transit
expected_dit = 10 * 1_000_000 * 0.2 / 8  # = 250000 bytes
check(abs(dit - expected_dit) < 1, f"Data in Transit(200ms, 10Mbps) = {dit:.0f} bytes (期望 ~250000)")

# Rolling RTT average
m2 = NetworkMetrics()
for i in range(10):
    m2.update_rtt(100.0 + i)
check(abs(m2.rtt_avg - 104.5) < 0.1, f"RTT 滑动平均 = {m2.rtt_avg:.1f} ms (期望 104.5)")

# Max samples window
m3 = NetworkMetrics()
for i in range(20):
    m3.update_rtt(float(i), max_samples=5)
check(len(m3.rtt_samples) == 5, f"RTT 窗口大小限制 = {len(m3.rtt_samples)} (期望 5)")
check(m3.rtt_samples[-1] == 19.0, f"RTT 窗口保留最新值 = {m3.rtt_samples[-1]}")

# Throughput EMA
m4 = NetworkMetrics()
m4.update_throughput(10.0)
check(abs(m4.throughput_avg - 10.0) < 0.01, f"首次吞吐量 = {m4.throughput_avg:.1f}")
m4.update_throughput(20.0)
expected_ema = 0.3 * 20.0 + 0.7 * 10.0
check(abs(m4.throughput_avg - expected_ema) < 0.01, f"吞吐量 EMA = {m4.throughput_avg:.1f} (期望 {expected_ema:.1f})")


# ============================================================
# 3. Quotes system
# ============================================================
section("3. 讽刺语录系统")

from lagdrive.quotes import (
    RTT_APOCALYPSE, RTT_FAST, PACKET_LOSS, TRAFFIC_HIGH,
    THROUGHPUT_LOW, NEUTRAL,
)

total_quotes = (len(RTT_APOCALYPSE) + len(RTT_FAST) + len(PACKET_LOSS)
                + len(TRAFFIC_HIGH) + len(THROUGHPUT_LOW) + len(NEUTRAL))
check(total_quotes >= 25, f"语录总数 = {total_quotes} (期望 >= 25)")

# Test category routing
q = select_quote(rtt_avg=1000, loss_rate=0, total_downloaded=0, throughput_avg=0, capacity=0)
check(q in RTT_APOCALYPSE, f"RTT > 800ms → 触发高延迟语录: \"{q[:40]}...\"")

q = select_quote(rtt_avg=20, loss_rate=0, total_downloaded=0, throughput_avg=0, capacity=0)
check(q in RTT_FAST, f"RTT < 50ms → 触发极速语录: \"{q[:40]}...\"")

q = select_quote(rtt_avg=0, loss_rate=0.99, total_downloaded=0, throughput_avg=0, capacity=0)
check(q in PACKET_LOSS, f"网络断开 → 触发丢包语录: \"{q[:40]}...\"")

q = select_quote(rtt_avg=100, loss_rate=0.1, total_downloaded=0, throughput_avg=0, capacity=0)
check(q in PACKET_LOSS, f"丢包 > 5%% → 触发丢包语录: \"{q[:40]}...\"")

q = select_quote(rtt_avg=100, loss_rate=0, total_downloaded=2_000_000_000, throughput_avg=0, capacity=0)
check(q in TRAFFIC_HIGH, f"流量 > 1GB → 触发流量语录: \"{q[:40]}...\"")


# ============================================================
# 4. BDP 计算 (API)
# ============================================================
section("4. BDP 计算 (API)")

bdp = LagDriveAPI.compute_bdp(100.0, 10.0)
check(bdp["capacity_bytes"] == expected_bdp, f"BDP API = {bdp['capacity_human']}")
check(bdp["capacity_human"] == "122.07 KB", f"容量格式化 = {bdp['capacity_human']}")

bdp_zero = LagDriveAPI.compute_bdp(0, 10.0)
check(bdp_zero["capacity_bytes"] == 0.0, "RTT=0 → 容量=0")

bdp_zero2 = LagDriveAPI.compute_bdp(100.0, 0)
check(bdp_zero2["capacity_bytes"] == 0.0, "带宽=0 → 容量=0")

# Large capacity
bdp_big = LagDriveAPI.compute_bdp(500.0, 100.0)
info(f"BDP(500ms, 100Mbps) = {bdp_big['capacity_human']}")
check(bdp_big["capacity_bytes"] > 1_000_000, "大延迟高带宽 → MB 级容量")


# ============================================================
# 5. Monitor 初始化 & Grid
# ============================================================
section("5. Monitor 初始化 & Grid")

config = MonitorConfig(target="1.1.1.1", port=80, grid_rows=10, grid_cols=10)
monitor = Monitor(config)

check(len(monitor.grid) == 10, "Grid 行数 = 10")
check(len(monitor.grid[0]) == 10, "Grid 列数 = 10")
check(all(cell.state == CellState.FREE for row in monitor.grid for cell in row),
      "初始状态: 所有 cell = FREE")

# Grid update with simulated metrics
monitor.metrics.rtt_avg = 500.0
monitor._update_grid()
active_count = sum(
    1 for row in monitor.grid for cell in row if cell.state == CellState.ACTIVE
)
check(active_count > 0, f"RTT=500ms 时 active cells = {active_count}")

# Grid with loss
monitor.metrics.rtt_avg = 200.0
monitor.metrics.loss_rate = 0.1
monitor._update_grid()
error_count = sum(
    1 for row in monitor.grid for cell in row if cell.state == CellState.ERROR
)
check(error_count > 0, f"10%% 丢包时 error cells = {error_count}")
info(f"Active: {100 - error_count}, Error: {error_count}")


# ============================================================
# 6. API snapshot
# ============================================================
section("6. API Snapshot 接口")

api = LagDriveAPI(target="1.1.1.1")
snap = api.snapshot()
check(snap["running"] is False, "初始状态: running = False")
check(snap["rtt_current"] == 0.0, "初始 RTT = 0")
check(snap["capacity"] == 0.0, "初始容量 = 0")
check("quote" in snap, "snapshot 包含 quote 字段")

# Grid API
grid = api.grid()
check(len(grid) == 10, "api.grid() 返回 10 行")
check(all(isinstance(c, str) for row in grid for c in row), "grid 单元格为字符串")

# Snapshot includes grid
check("grid" in snap, "snapshot 包含 grid 字段")
if "grid" in snap:
    check(len(snap["grid"]) == 10, "snapshot.grid 行数 = 10")

# Public API properties
check(api.storage_enabled is False, "api.storage_enabled = False (未启用)")
check(api.target == "1.1.1.1", "api.target = '1.1.1.1'")
check(api.port == 80, "api.port = 80")


# ============================================================
# 7. Dashboard 初始化 (无网络)
# ============================================================
section("7. Dashboard 初始化 (不启动 Live)")

from lagdrive.dashboard import Dashboard
dash = Dashboard()
check(dash._live is None, "Dashboard 初始无 Live 实例")
check(dash._quote == "", "Dashboard 初始无语录")

# Test format_bytes helper
check(Dashboard._format_bytes(0) == ("0.0", "B"), "format_bytes(0) = '0.0 B'")
check(Dashboard._format_bytes(1024) == ("1.0", "KB"), "format_bytes(1024) = '1.0 KB'")
check(Dashboard._format_bytes(1048576) == ("1.0", "MB"), "format_bytes(1MB) = '1.0 MB'")
check(Dashboard._format_bytes(1073741824) == ("1.0", "GB"), "format_bytes(1GB) = '1.0 GB'")

# Test rtt_color
from lagdrive.dashboard import STYLES
check(Dashboard._rtt_color(30) == STYLES["stat_good"], "RTT < 50ms → stat_good")
check(Dashboard._rtt_color(1000) == STYLES["stat_bad"], "RTT > 500ms → stat_bad")


# ============================================================
# 8. 网络探测 (可选)
# ============================================================
run_network = "--network" in sys.argv or "--all" in sys.argv
skip_network = "--quick" in sys.argv

if not skip_network:
    section("8. 网络探测 (真实 TCP)")

    info("RTT 探测 → 1.1.1.1:80 ...")
    rtt_result = LagDriveAPI.probe_rtt("1.1.1.1", 80, count=3, timeout=5.0)
    if rtt_result["success"] > 0:
        check(True, f"RTT = {rtt_result['avg_ms']} ms  ({rtt_result['success']}/3 成功)")
    else:
        info("RTT 探测失败 (可能是网络限制, 跳过)")
        info("使用 --quick 跳过网络测试")

    info("RTT 探测 → 8.8.8.8:53 ...")
    rtt_result2 = LagDriveAPI.probe_rtt("8.8.8.8", 53, count=3, timeout=5.0)
    if rtt_result2["success"] > 0:
        check(True, f"RTT = {rtt_result2['avg_ms']} ms  ({rtt_result2['success']}/3 成功)")
    else:
        info("RTT 探测失败 (可能是网络限制, 跳过)")

    if run_network:
        info("吞吐量测试 (可能需要 10-30 秒)...")
        tp_result = LagDriveAPI.probe_throughput(test_size=5_000_000)
        if "error" not in tp_result:
            check(True, f"吞吐量 = {tp_result['mbps']} Mbps  ({tp_result['bytes_downloaded']:,} bytes)")
        else:
            info(f"吞吐量测试失败: {tp_result.get('error', 'unknown')}")


# ============================================================
# 9. Monitor 生命周期 (短暂)
# ============================================================
section("9. Monitor 生命周期测试")

if skip_network:
    info("--quick: 跳过 Monitor 生命周期测试 (需要网络)")
else:
    api2 = LagDriveAPI(target="1.1.1.1", port=80, probe_interval=1.0)
    check(not api2.running, "启动前 running = False")

    api2.start()
    deadline = time.monotonic() + 5.0
    while not api2.running and time.monotonic() < deadline:
        time.sleep(0.1)
    check(api2.running, "启动后 running = True")

    time.sleep(10.0)
    snap2 = api2.snapshot()
    check(snap2["probe_count"] > 0, f"探测计数 = {snap2['probe_count']} (> 0)")
    info(f"RTT: {snap2['rtt_current']:.1f} ms, Loss: {snap2['loss_rate']*100:.1f}%")

    api2.stop()
    deadline = time.monotonic() + 5.0
    while api2.running and time.monotonic() < deadline:
        time.sleep(0.1)
    check(not api2.running, "停止后 running = False")


# ============================================================
# 10. 线协议 (Wire Protocol)
# ============================================================
section("10. 线协议测试")

from lagdrive.relay import LagDriveProtocol, TYPE_WRITE, TYPE_ECHO, MAGIC

# Encode/decode roundtrip
test_data = b"Hello, LagDrive!"
frame = LagDriveProtocol.encode_write(block_id=42, offset=100, data=test_data)
check(frame[:2] == MAGIC, "帧头 magic = b'LD'")
check(len(frame) == 7 + 8 + 8 + len(test_data), f"帧总长度 = {len(frame)} bytes")

# Simulate decode via a mock socket
import io

class MockSocket:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
    def recv(self, n: int) -> bytes:
        return self._buf.read(n)

mock = MockSocket(frame)
result = LagDriveProtocol.decode_frame(mock)
check(result is not None, "decode_frame 返回非 None")
if result is not None:
    ftype, body = result
    check(ftype == TYPE_WRITE, f"帧类型 = WRITE (0x{ftype:02x})")
    decoded = LagDriveProtocol.decode_block_body(body)
    check(decoded is not None, "decode_block_body 成功")
    if decoded is not None:
        bid, off, data = decoded
        check(bid == 42, f"block_id = {bid} (期望 42)")
        check(off == 100, f"offset = {off} (期望 100)")
        check(data == test_data, f"data = {data!r}")

# Empty body
empty_frame = LagDriveProtocol.encode_frame(TYPE_WRITE, b'')
mock2 = MockSocket(empty_frame)
result2 = LagDriveProtocol.decode_frame(mock2)
check(result2 is not None and result2[1] == b'', "空 body 帧正确处理")

# Bad magic
bad_magic = b'\xff\xff' + frame[2:]
mock3 = MockSocket(bad_magic)
result3 = LagDriveProtocol.decode_frame(mock3)
check(result3 is None, "错误 magic → 返回 None")


# ============================================================
# 11. RingBuffer 单元测试 (无网络)
# ============================================================
section("11. RingBuffer 单元测试")

from lagdrive.storage import RingBuffer
from time import monotonic

rb = RingBuffer(max_bytes=1000, max_blocks=10, block_size=100)

# Basic write/read
blocks = rb.write(b"hello world")
check(len(blocks) == 1, f"写入 11 bytes → {len(blocks)} 个 block")
check(blocks[0].data == b"hello world", "block 数据正确")
check(blocks[0].offset == 0, "首个 block offset = 0")

data = rb.read(0, 11)
check(data == b"hello world", f"读回数据 = {data!r}")

# Multi-block write
big_data = b"A" * 250
blocks2 = rb.write(big_data)
check(len(blocks2) == 3, f"250 bytes / 100 block_size → {len(blocks2)} 个 blocks")

data2 = rb.read(11, 250)
check(len(data2) == 250, f"读回 250 bytes")
check(data2 == big_data, "大数据读回正确")

# Expired blocks return zeros
rb2 = RingBuffer(max_bytes=10000, max_blocks=10, block_size=100)
old_blocks = rb2.write(b"will expire")
# Fake the send_time to be very old
for b in rb2._blocks.values():
    b.send_time = monotonic() - 100.0
expired = rb2.expire_stale_blocks(50.0)
check(expired > 0, f"过期了 {expired} 个 block")
data3 = rb2.read(0, 11)
check(data3 == b'\x00' * 11, "过期 block 读回全零")

# Capacity eviction
rb3 = RingBuffer(max_bytes=200, max_blocks=10, block_size=100)
rb3.write(b"A" * 100)
rb3.write(b"B" * 100)
check(rb3.stats["total_blocks"] == 2, "2 个 blocks")
rb3.write(b"C" * 100)
check(rb3.stats["total_blocks"] == 2, f"超容量后淘汰到 {rb3.stats['total_blocks']} 个 blocks")

# Confirm block
rb4 = RingBuffer(max_bytes=1000, max_blocks=10, block_size=100)
blks = rb4.write(b"confirm me")
check(blks[0].confirmed is False, "写入后未确认")
ok_result = rb4.confirm_block(blks[0].block_id)
check(ok_result is True, "confirm 成功")
check(blks[0].confirmed is True, "已确认")

# Stats
stats = rb4.stats
check(stats["confirmed_blocks"] == 1, f"confirmed_blocks = {stats['confirmed_blocks']}")
check("lost_bytes" in stats, "stats 包含 lost_bytes")


# ============================================================
# 12. Echo Relay 本地测试
# ============================================================
section("12. Echo Relay 本地集成测试")

import socket as _socket
from lagdrive.relay import EchoRelay

relay = EchoRelay("127.0.0.1", 0)  # port 0 = auto-assign
relay._server = relay._create_server()
actual_port = relay._server.server_address[1]
relay._thread = __import__('threading').Thread(target=relay._server.serve_forever, daemon=True)
relay._thread.start()
time.sleep(0.2)

try:
    # Connect and send WRITE frame
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        sock.connect(("127.0.0.1", actual_port))
        write_frame = LagDriveProtocol.encode_write(block_id=1, offset=0, data=b"relay test")
        sock.sendall(write_frame)

        # Read ECHO frame
        sock.settimeout(3.0)
        echo_result = LagDriveProtocol.decode_frame(sock)
        check(echo_result is not None, "收到 ECHO 帧")
        if echo_result is not None:
            etype, ebody = echo_result
            check(etype == TYPE_ECHO, f"ECHO 类型正确 (0x{etype:02x})")
            decoded = LagDriveProtocol.decode_block_body(ebody)
            if decoded is not None:
                bid, off, data = decoded
                check(bid == 1, f"block_id = {bid}")
                check(data == b"relay test", f"数据 = {data!r}")

        # Send multiple frames
        for i in range(5):
            f = LagDriveProtocol.encode_write(block_id=i + 10, offset=i * 100, data=f"frame-{i}".encode())
            sock.sendall(f)
        for i in range(5):
            sock.settimeout(3.0)
            r = LagDriveProtocol.decode_frame(sock)
            check(r is not None and r[0] == TYPE_ECHO, f"多帧 echo #{i+1} 成功")
    finally:
        sock.close()
except Exception as e:
    check(False, f"Relay 测试异常: {e}")

relay.stop()
time.sleep(0.3)
check(relay._server is None, "Relay 正常关闭")


# ============================================================
# 13. StorageClient 集成测试 (本地 Relay)
# ============================================================
section("13. StorageClient + Relay 集成测试")

from lagdrive.storage import StorageClient

# Start relay on random port
relay2 = EchoRelay("127.0.0.1", 0)
relay2._server = relay2._create_server()
port2 = relay2._server.server_address[1]
relay2._thread = __import__('threading').Thread(target=relay2._server.serve_forever, daemon=True)
relay2._thread.start()
time.sleep(0.2)

try:
    client = StorageClient("127.0.0.1", port2)
    client.connect()
    time.sleep(0.2)
    check(client.connected, "StorageClient 已连接")

    # Write and read
    write_result = client.write(b"Hello, network storage!")
    check(write_result["blocks_written"] >= 1, f"写入 {write_result['blocks_written']} 个 blocks")
    check(write_result["bytes_written"] == 23, f"写入 23 bytes")

    read_data = client.read(0, 23)
    check(read_data == b"Hello, network storage!", f"读回 = {read_data!r}")

    # Wait for echo confirmation
    time.sleep(0.5)
    stats = client.stats
    check(stats["confirmed_blocks"] >= 1, f"已确认 {stats['confirmed_blocks']} 个 blocks")
    check(stats["relay_connected"] is True, "relay_connected = True")

    # Disconnect and verify
    client.disconnect()
    time.sleep(0.2)
    check(not client.connected, "断开后 connected = False")

except Exception as e:
    check(False, f"StorageClient 测试异常: {e}")

relay2.stop()


# ============================================================
# 14. Models 新增类型测试
# ============================================================
section("14. Models 新增类型测试")

check(CellState.STORED.value == "stored", "CellState.STORED = 'stored'")

from lagdrive.models import StorageBlock, StorageState
from time import monotonic

sb = StorageBlock(block_id=1, data=b"test", offset=0, send_time=monotonic())
check(sb.size == 4, f"StorageBlock.size = {sb.size}")
check(sb.confirmed is False, "初始未确认")
check(sb.expired is False, "初始未过期")
check(sb.is_parity == -1, "初始非校验块 (is_parity = -1)")

ss = StorageState()
check(ss.used_bytes == 0, "StorageState 初始 used_bytes = 0")
check(ss.relay_connected is False, "初始未连接")


# ============================================================
# 15. RAIDMode 枚举测试
# ============================================================
section("15. RAIDMode 枚举测试")

from lagdrive.models import RAIDMode

check(RAIDMode.NONE.value == "none", "RAIDMode.NONE = 'none'")
check(RAIDMode.RAID0.value == "raid0", "RAIDMode.RAID0 = 'raid0'")
check(RAIDMode.RAID1.value == "raid1", "RAIDMode.RAID1 = 'raid1'")
check(RAIDMode.RAID5.value == "raid5", "RAIDMode.RAID5 = 'raid5'")
check(RAIDMode.RAID10.value == "raid10", "RAIDMode.RAID10 = 'raid10'")

# RAIDMode from string
check(RAIDMode("raid0") == RAIDMode.RAID0, "RAIDMode('raid0') = RAID0")
check(RAIDMode("raid5") == RAIDMode.RAID5, "RAIDMode('raid5') = RAID5")


# ============================================================
# 16. RAIDStorageClient 单元测试 (无网络)
# ============================================================
section("16. RAIDStorageClient 单元测试 (无网络)")

from lagdrive.raid import RAIDStorageClient

# Validation — need >= 2 relays
try:
    RAIDStorageClient(relays=[("127.0.0.1", 9527)], mode=RAIDMode.RAID0)
    check(False, "1 relay 应该抛异常")
except ValueError:
    check(True, "1 relay → ValueError")

# RAID 5 needs >= 3
try:
    RAIDStorageClient(
        relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528)],
        mode=RAIDMode.RAID5,
    )
    check(False, "RAID 5 + 2 relays 应该抛异常")
except ValueError:
    check(True, "RAID 5 + 2 relays → ValueError")

# RAID 10 needs >= 4 and even
try:
    RAIDStorageClient(
        relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528), ("127.0.0.1", 9529)],
        mode=RAIDMode.RAID10,
    )
    check(False, "RAID 10 + 3 relays 应该抛异常")
except ValueError:
    check(True, "RAID 10 + 3 relays → ValueError")

# Valid construction
try:
    rc = RAIDStorageClient(
        relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528)],
        mode=RAIDMode.RAID0,
    )
    check(True, "RAIDStorageClient(RAID0, 2 relays) 构造成功")
    check(rc.mode == RAIDMode.RAID0, f"mode = {rc.mode.value}")
    check(len(rc.relays) == 2, f"relays count = {len(rc.relays)}")
except Exception as e:
    check(False, f"RAIDStorageClient 构造失败: {e}")

# Valid RAID 5 construction
try:
    rc5 = RAIDStorageClient(
        relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528), ("127.0.0.1", 9529)],
        mode=RAIDMode.RAID5,
    )
    check(True, "RAIDStorageClient(RAID5, 3 relays) 构造成功")
except Exception as e:
    check(False, f"RAIDStorageClient RAID5 构造失败: {e}")

# Valid RAID 10 construction
try:
    rc10 = RAIDStorageClient(
        relays=[
            ("127.0.0.1", 9527), ("127.0.0.1", 9528),
            ("127.0.0.1", 9529), ("127.0.0.1", 9530),
        ],
        mode=RAIDMode.RAID10,
    )
    check(True, "RAIDStorageClient(RAID10, 4 relays) 构造成功")
except Exception as e:
    check(False, f"RAIDStorageClient RAID10 构造失败: {e}")


# ============================================================
# 17. RAID 目标分发逻辑测试 (无网络)
# ============================================================
section("17. RAID 目标分发逻辑测试 (无网络)")

# RAID 0 — round-robin
rc0 = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID0,
)
targets_b0 = rc0._get_targets(
    StorageBlock(block_id=0, data=b"x", offset=0, send_time=0), 3
)
targets_b1 = rc0._get_targets(
    StorageBlock(block_id=1, data=b"x", offset=0, send_time=0), 3
)
targets_b2 = rc0._get_targets(
    StorageBlock(block_id=2, data=b"x", offset=0, send_time=0), 3
)
check(targets_b0 == [0], f"RAID0 block0 → relay {targets_b0}")
check(targets_b1 == [1], f"RAID0 block1 → relay {targets_b1}")
check(targets_b2 == [2], f"RAID0 block2 → relay {targets_b2}")

# RAID 1 — all relays
rc1 = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0)],
    mode=RAIDMode.RAID1,
)
targets_m = rc1._get_targets(
    StorageBlock(block_id=0, data=b"x", offset=0, send_time=0), 2
)
check(targets_m == [0, 1], f"RAID1 block0 → relays {targets_m}")

# RAID 5 — data and parity targets (3 relays, stripe_size=2)
# Stripe 0 parity → relay 0; data blocks → relays 1, 2
rc5test = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID5,
)
targets_5_0 = rc5test._get_targets(
    StorageBlock(block_id=0, data=b"x", offset=0, send_time=0), 3
)
targets_5_1 = rc5test._get_targets(
    StorageBlock(block_id=1, data=b"x", offset=0, send_time=0), 3
)
# Stripe 1 parity → relay 1; data blocks → relays 0, 2
targets_5_2 = rc5test._get_targets(
    StorageBlock(block_id=2, data=b"x", offset=0, send_time=0), 3
)
check(targets_5_0 == [1], f"RAID5 block0 → relay {targets_5_0} (parity on 0)")
check(targets_5_1 == [2], f"RAID5 block1 → relay {targets_5_1} (parity on 0)")
check(targets_5_2 == [0], f"RAID5 block2 → relay {targets_5_2} (parity on 1)")

# RAID 10 — mirrored pairs
rc10test = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0), ("h3", 0)],
    mode=RAIDMode.RAID10,
)
targets_10_0 = rc10test._get_targets(
    StorageBlock(block_id=0, data=b"x", offset=0, send_time=0), 4
)
targets_10_1 = rc10test._get_targets(
    StorageBlock(block_id=1, data=b"x", offset=0, send_time=0), 4
)
check(targets_10_0 == [0, 1], f"RAID10 block0 → pair {targets_10_0}")
check(targets_10_1 == [2, 3], f"RAID10 block1 → pair {targets_10_1}")


# ============================================================
# 18. RAID 5 奇偶校验计算测试 (无网络)
# ============================================================
section("18. RAID 5 奇偶校验计算测试 (无网络)")

from lagdrive.storage import RingBuffer

# Create RAID5 client (3 relays)
rc5parity = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID5,
)

# Manually test parity computation
data_a = b'\xff\x00\xff\x00'
data_b = b'\x00\xff\x00\xff'
expected_parity = bytes(a ^ b for a, b in zip(data_a, data_b))
check(expected_parity == b'\xff\xff\xff\xff', f"XOR 校验 = {expected_parity.hex()}")

# Build parity from ring buffer blocks (block_size=4 → each 4-byte chunk = 1 block)
ring_p = RingBuffer(max_bytes=100000, block_size=4)
blocks = ring_p.write(data_a + data_b)  # 2 blocks: data_a and data_b
check(len(blocks) == 2, f"8 bytes / 4 block_size = {len(blocks)} blocks")
parity_blocks = rc5parity._build_raid5_parity(blocks, stripe_size=2, ring=ring_p)
check(len(parity_blocks) == 1, f"2 数据块 → {len(parity_blocks)} 个校验块")
check(parity_blocks[0].is_parity >= 0, f"parity block.is_parity = {parity_blocks[0].is_parity} (relay index)")

# Verify parity data is correct XOR of the two data blocks
computed_xor = bytes(a ^ b for a, b in zip(blocks[0].data, blocks[1].data))
check(parity_blocks[0].data == computed_xor, "校验块 = XOR(数据块0, 数据块1)")

# Parity IDs don't collide with data block IDs
data_ids = {b.block_id for b in blocks}
parity_ids = {b.block_id for b in parity_blocks}
check(data_ids.isdisjoint(parity_ids), "校验块 ID 不与数据块 ID 冲突")


# ============================================================
# 19. RingBuffer parity block 排除测试 (无网络)
# ============================================================
section("19. RingBuffer 校验块排除测试 (无网络)")

ring_ep = RingBuffer(max_bytes=100000, block_size=100)

# Write normal data
data_blocks = ring_ep.write(b"hello world")
check(len(data_blocks) == 1, "普通写入 1 block")

# Write a parity block
parity_block = ring_ep.write(b"parity data", is_parity=0)  # parity relay 0
check(len(parity_block) == 1, "校验写入 1 block")
check(parity_block[0].is_parity >= 0, f"is_parity = {parity_block[0].is_parity}")

# Read should return data blocks but skip parity
read_data = ring_ep.read(0, 11)
check(read_data == b"hello world", f"读回数据不含校验: {read_data!r}")

# Stats should include parity block
stats_ep = ring_ep.stats
check(stats_ep["total_blocks"] == 2, f"total_blocks = {stats_ep['total_blocks']} (含校验)")


# ============================================================
# 20. RAID + 多 Relay 集成测试
# ============================================================
section("20. RAID + 多 Relay 集成测试")

skip_raid_relay = skip_network  # Reuse --quick flag

if skip_raid_relay:
    info("--quick: 跳过 RAID Relay 集成测试 (需要本地 Relay)")
else:
    # Start 3 relays for RAID 5
    from lagdrive.relay import EchoRelay
    relays_list = []
    relay_servers = []
    for i in range(3):
        r = EchoRelay("127.0.0.1", 0)
        r._server = r._create_server()
        port = r._server.server_address[1]
        r._thread = __import__('threading').Thread(
            target=r._server.serve_forever, daemon=True
        )
        r._thread.start()
        relays_list.append(("127.0.0.1", port))
        relay_servers.append(r)
    time.sleep(0.3)

    try:
        # RAID 0 — test striping
        raid0 = RAIDStorageClient(
            relays=relays_list[:2], mode=RAIDMode.RAID0, block_size=100,
        )
        raid0.connect()
        time.sleep(0.2)
        check(raid0.connected, "RAID0 已连接")

        data_raid0 = b"RAID0 striping test data here!!"
        w0 = raid0.write(data_raid0)
        check(w0["blocks_written"] >= 1, f"RAID0 写入 {w0['blocks_written']} blocks")
        check(w0["raid_mode"] == "raid0", f"raid_mode = {w0['raid_mode']}")
        read0 = raid0.read(0, len(data_raid0))
        check(read0 == data_raid0, f"RAID0 读回 = {read0!r}")
        raid0.disconnect()

        # RAID 1 — test mirroring
        data_raid1 = b"RAID1 mirror!"
        raid1 = RAIDStorageClient(
            relays=relays_list[:2], mode=RAIDMode.RAID1, block_size=100,
        )
        raid1.connect()
        time.sleep(0.2)
        w1 = raid1.write(data_raid1)
        check(w1["blocks_written"] >= 1, f"RAID1 写入 {w1['blocks_written']} blocks")
        check(w1["raid_mode"] == "raid1", f"raid_mode = {w1['raid_mode']}")
        check(w1["physical_sends"] >= 2, f"RAID1 physical_sends = {w1['physical_sends']} (镜像)")
        read1 = raid1.read(0, len(data_raid1))
        check(read1 == data_raid1, f"RAID1 读回 = {read1!r}")
        raid1.disconnect()

        # RAID 5 — test striping + parity
        data_raid5 = b"RAID5 parity test"
        raid5 = RAIDStorageClient(
            relays=relays_list, mode=RAIDMode.RAID5, block_size=100,
        )
        raid5.connect()
        time.sleep(0.2)
        w5 = raid5.write(data_raid5)
        check(w5["blocks_written"] >= 1, f"RAID5 写入 {w5['blocks_written']} blocks")
        check(w5["raid_mode"] == "raid5", f"raid_mode = {w5['raid_mode']}")
        read5 = raid5.read(0, len(data_raid5))
        check(read5 == data_raid5, f"RAID5 读回 = {read5!r}")

        # Verify stats
        s5 = raid5.stats
        check(s5["raid_mode"] == "raid5", f"stats raid_mode = {s5['raid_mode']}")
        check(s5["relay_count"] == 3, f"stats relay_count = {s5['relay_count']}")
        raid5.disconnect()

        # RAID 10 — test mirror + stripe (need 4 relays)
        relay4 = EchoRelay("127.0.0.1", 0)
        relay4._server = relay4._create_server()
        port4 = relay4._server.server_address[1]
        relay4._thread = __import__('threading').Thread(
            target=relay4._server.serve_forever, daemon=True
        )
        relay4._thread.start()
        relays_4 = relays_list + [("127.0.0.1", port4)]
        time.sleep(0.2)

        data_raid10 = b"RAID10 test data"
        raid10 = RAIDStorageClient(
            relays=relays_4, mode=RAIDMode.RAID10, block_size=100,
        )
        raid10.connect()
        time.sleep(0.2)
        w10 = raid10.write(data_raid10)
        check(w10["blocks_written"] >= 1, f"RAID10 写入 {w10['blocks_written']} blocks")
        check(w10["raid_mode"] == "raid10", f"raid_mode = {w10['raid_mode']}")
        read10 = raid10.read(0, len(data_raid10))
        check(read10 == data_raid10, f"RAID10 读回 = {read10!r}")
        raid10.disconnect()
        relay4.stop()

    except Exception as e:
        check(False, f"RAID 集成测试异常: {e}")

    for rs in relay_servers:
        rs.stop()
    time.sleep(0.2)


# ============================================================
# 21. RAID 容量缩放测试 (Monitor)
# ============================================================
section("21. RAID 容量缩放测试 (Monitor)")

from lagdrive.monitor import MonitorConfig

cfg_raid0 = MonitorConfig(
    raid_mode=RAIDMode.RAID0,
    relays=[("h", 0), ("h", 1), ("h", 2)],
)
m_raid = Monitor(cfg_raid0)
base_bdp = 100000.0
scaled = m_raid._raid_capacity(base_bdp)
check(scaled == base_bdp * 3, f"RAID0 容量 = {scaled} (期望 {base_bdp * 3})")

cfg_raid1 = MonitorConfig(raid_mode=RAIDMode.RAID1, relays=[("h", 0), ("h", 1)])
m_raid1 = Monitor(cfg_raid1)
check(m_raid1._raid_capacity(base_bdp) == base_bdp, "RAID1 容量 = base")

cfg_raid5 = MonitorConfig(
    raid_mode=RAIDMode.RAID5,
    relays=[("h", 0), ("h", 1), ("h", 2)],
)
m_raid5 = Monitor(cfg_raid5)
check(m_raid5._raid_capacity(base_bdp) == base_bdp * 2, "RAID5 (3 relays) 容量 = 2x base")

cfg_raid10 = MonitorConfig(
    raid_mode=RAIDMode.RAID10,
    relays=[("h", 0), ("h", 1), ("h", 2), ("h", 3)],
)
m_raid10 = Monitor(cfg_raid10)
check(m_raid10._raid_capacity(base_bdp) == base_bdp * 2, "RAID10 (4 relays) 容量 = 2x base")


# ============================================================
# 22. RAID 讽刺语录测试
# ============================================================
section("22. RAID 讽刺语录测试")

from lagdrive.quotes import RAID_STRIPED, RAID_MIRRORED, RAID_PARITY, RAID_TEN

check(len(RAID_STRIPED) >= 3, f"RAID 条带语录 = {len(RAID_STRIPED)} 条")
check(len(RAID_MIRRORED) >= 3, f"RAID 镜像语录 = {len(RAID_MIRRORED)} 条")
check(len(RAID_PARITY) >= 3, f"RAID 校验语录 = {len(RAID_PARITY)} 条")
check(len(RAID_TEN) >= 3, f"RAID10 语录 = {len(RAID_TEN)} 条")

q_raid0 = select_quote(0, 0, 0, 0, 0, storage_event="raid0")
check(q_raid0 in RAID_STRIPED, f"raid0 → 条带语录: \"{q_raid0[:30]}...\"")

q_raid1 = select_quote(0, 0, 0, 0, 0, storage_event="raid1")
check(q_raid1 in RAID_MIRRORED, f"raid1 → 镜像语录: \"{q_raid1[:30]}...\"")

q_raid5 = select_quote(0, 0, 0, 0, 0, storage_event="raid5")
check(q_raid5 in RAID_PARITY, f"raid5 → 校验语录: \"{q_raid5[:30]}...\"")

q_raid10 = select_quote(0, 0, 0, 0, 0, storage_event="raid10")
check(q_raid10 in RAID_TEN, f"raid10 → RAID10 语录: \"{q_raid10[:30]}...\"")


# ============================================================
# 23. LagDriveAPI RAID 接口测试
# ============================================================
section("23. LagDriveAPI RAID 接口测试")

api_raid = LagDriveAPI(
    target="1.1.1.1",
    raid_mode="raid0",
    relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528)],
)
check(api_raid._config.raid_mode == RAIDMode.RAID0, "API RAID 模式 = RAID0")
check(len(api_raid._config.relays) == 2, "API relays count = 2")

# Enable RAID via API method (without connecting)
api_raid2 = LagDriveAPI(target="1.1.1.1")
check(api_raid2._config.raid_mode == RAIDMode.NONE, "API 默认 RAID = NONE")


# ============================================================
# 19b. RAID 5 XOR Reconstruction Tests (no network)
# ============================================================
section("19b. RAID 5 XOR 重建测试 (无网络)")

from lagdrive.models import RelayHealth, PerRelayRTT

# Build parity and test reconstruction
rc5_recon = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID5,
    block_size=10,
)
ring_recon = RingBuffer(max_bytes=100000, block_size=10)
rc5_recon._ring = ring_recon  # share the same ring

# Write two data blocks + parity
d_blocks = ring_recon.write(b"A" * 10 + b"B" * 10)
check(len(d_blocks) == 2, f"2 data blocks from 20 bytes / block_size=10")
p_blocks = rc5_recon._build_raid5_parity(d_blocks, stripe_size=2, ring=ring_recon)
check(len(p_blocks) == 1, "1 parity block for 2 data blocks")

# Expire block 0, preserving data
d_blocks[0].expired = True
d_blocks[0]._original_data = d_blocks[0].data
d_blocks[0].data = b'\x00' * 10

# Reconstruct block 0 from parity + surviving block 1
recovered = rc5_recon._reconstruct_block(d_blocks[0].block_id, 10)
check(recovered == b"A" * 10, f"Reconstructed block 0 = {recovered!r}")

# Reconstruct block 1 from parity + surviving block 0
d_blocks[0].expired = False
d_blocks[0].data = d_blocks[0]._original_data
d_blocks[1].expired = True
d_blocks[1]._original_data = d_blocks[1].data
d_blocks[1].data = b'\x00' * 10

recovered1 = rc5_recon._reconstruct_block(d_blocks[1].block_id, 10)
check(recovered1 == b"B" * 10, f"Reconstructed block 1 = {recovered1!r}")

# _has_parity check
check(rc5_recon._has_parity(d_blocks[0].block_id), "_has_parity returns True for stripe")

# Test with send_failed flag
d_blocks[1].expired = False
d_blocks[1].send_failed = True
d_blocks[1].data = d_blocks[1]._original_data
recovered_sf = rc5_recon._reconstruct_block(d_blocks[1].block_id, 10)
check(recovered_sf == b"B" * 10, "Reconstruction works for send_failed blocks too")


# ============================================================
# 19c. RelayHealth & PerRelayRTT Tests (no network)
# ============================================================
section("19c. RelayHealth & PerRelayRTT 测试 (无网络)")

# RelayHealth
rh = RelayHealth(address=("127.0.0.1", 9527))
check(rh.alive is True, "Initial relay health = alive")
check(rh.consecutive_failures == 0, "Initial failures = 0")
check(rh.total_sends == 0, "Initial sends = 0")

# PerRelayRTT
rtt_t = PerRelayRTT()
rtt_t.update(50.0)
rtt_t.update(60.0)
rtt_t.update(70.0)
check(abs(rtt_t.avg - 60.0) < 0.1, f"Per-relay RTT avg = {rtt_t.avg:.1f} (expect 60.0)")
check(rtt_t.current == 70.0, f"Per-relay RTT current = {rtt_t.current}")
check(len(rtt_t.samples) == 3, f"Per-relay RTT samples = {len(rtt_t.samples)}")

# Sliding window overflow
rtt_big = PerRelayRTT()
for i in range(20):
    rtt_big.update(float(i))
check(len(rtt_big.samples) == 15, f"Sliding window capped at 15 (got {len(rtt_big.samples)})")
check(rtt_big.current == 19.0, f"Last value = {rtt_big.current}")

# Relay health in RAIDStorageClient
check(len(rc5_recon._relay_health) == 3, "3 relay health entries")
check(rc5_recon._relay_health[0].address == ("h0", 0), "Relay 0 address = h0:0")

# Per-relay RTT in RAIDStorageClient
check(len(rc5_recon._relay_rtt) == 3, "3 relay RTT trackers")
check("relay_rtt" in rc5_recon.stats, "stats includes relay_rtt")
check("relay_health" in rc5_recon.stats, "stats includes relay_health")
check("degraded" in rc5_recon.stats, "stats includes degraded flag")
check(rc5_recon.stats["degraded"] is False, "Initially not degraded")


# ============================================================
# 19d. Degraded Read Path Tests (no network)
# ============================================================
section("19d. 降级读取测试 (无网络)")

# RAID5 degraded read: one block expired, reconstruct from parity
rc5_dr = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID5,
    block_size=10,
)
ring_dr = RingBuffer(max_bytes=100000, block_size=10)
rc5_dr._ring = ring_dr

test_data = b"HELLO" * 2 + b"WORLD" * 2  # 20 bytes = 2 blocks of 10
dr_blocks = ring_dr.write(test_data)
check(len(dr_blocks) == 2, "Degraded read: 2 data blocks written")

dr_parity = rc5_dr._build_raid5_parity(dr_blocks, stripe_size=2, ring=ring_dr)
check(len(dr_parity) == 1, "Degraded read: 1 parity block")

# Normal read (all blocks alive)
normal_read = rc5_dr.read(0, 20)
check(normal_read == test_data, f"Normal read = {normal_read!r}")

# Expire block 0
dr_blocks[0].expired = True
dr_blocks[0]._original_data = dr_blocks[0].data
dr_blocks[0].data = b'\x00' * 10

# Degraded read should reconstruct block 0 from parity
degraded_read = rc5_dr.read(0, 20)
check(degraded_read == test_data, f"Degraded read reconstructed = {degraded_read!r}")

# Read a subset (only the reconstructed block)
partial = rc5_dr.read(0, 10)
check(partial == b"HELLO" * 2, f"Partial degraded read block 0 = {partial!r}")

# Non-RAID5 mode: no reconstruction
rc5_dr.mode = RAIDMode.RAID0
no_recon = rc5_dr.read(0, 20)
check(no_recon[:10] == b'\x00' * 10, "RAID0 mode: no reconstruction, zeros for expired")


# ============================================================
# 22b. Per-Relay RTT in Stats & Degraded Quotes
# ============================================================
section("22b. Per-Relay RTT 统计 & 降级语录测试")

# Per-relay RTT in stats
rc5_rtt = RAIDStorageClient(
    relays=[("h0", 0), ("h1", 0), ("h2", 0)],
    mode=RAIDMode.RAID5,
)
st = rc5_rtt.stats
check("relay_rtt" in st, "stats has relay_rtt")
check(len(st["relay_rtt"]) == 3, "3 relay RTT entries")
check(st["relay_rtt"][0]["avg_ms"] == 0.0, "Initial relay RTT avg = 0")
check("relay_alive_count" in st, "stats has relay_alive_count")
check(st["relay_alive_count"] == 3, "All 3 relays alive initially")
check(st["dead_relays"] == [], "No dead relays initially")

# Simulate relay failure
rc5_rtt._relay_health[1].alive = False
rc5_rtt._relay_health[1].consecutive_failures = 5
st2 = rc5_rtt.stats
check(st2["degraded"] is True, "degraded = True after relay failure")
check(st2["relay_alive_count"] == 2, "2 relays alive after failure")
check(st2["relay_dead_count"] == 1, "1 relay dead")
check(len(st2["dead_relays"]) == 1, "1 dead relay in list")
check(st2["dead_relays"][0]["index"] == 1, "Dead relay index = 1")
check(st2["relay_connected"] is True, "Still connected (at least 1 alive)")

# Degraded quotes
from lagdrive.quotes import RAID_DEGRADED, RAID_REBUILT
q_degraded = select_quote(0, 0, 0, 0, 0, storage_event="raid_degraded")
check(q_degraded in RAID_DEGRADED, f"raid_degraded quote: \"{q_degraded[:30]}...\"")

q_rebuilt = select_quote(0, 0, 0, 0, 0, storage_event="raid_rebuilt")
check(q_rebuilt in RAID_REBUILT, f"raid_rebuilt quote: \"{q_rebuilt[:30]}...\"")


# ============================================================
# 23b. RAID Mode Switch API Test (no network)
# ============================================================
section("23b. RAID 模式切换 API 测试 (无网络)")

api_switch = LagDriveAPI(target="1.1.1.1")
check(api_switch._config.raid_mode == RAIDMode.NONE, "Initial mode = NONE")

# switch_raid_mode method exists
check(hasattr(api_switch, 'switch_raid_mode'), "switch_raid_mode method exists")

# StorageBlock new fields
from lagdrive.models import StorageBlock
sb_new = StorageBlock(block_id=0, data=b"test", offset=0, send_time=0.0)
check(sb_new.relay_targets == [], "StorageBlock.relay_targets defaults to []")
check(sb_new.send_failed is False, "StorageBlock.send_failed defaults to False")
check(sb_new._original_data == b'', "StorageBlock._original_data defaults to b''")


# ============================================================
# Summary
# ============================================================
section("测试结果")
total = passed + failed
print(f"  {GREEN}通过: {passed}{RESET}  {RED}失败: {failed}{RESET}  总计: {total}")
if failed == 0:
    print(f"\n  {GREEN}{BOLD}全部通过! LagDrive 核心功能正常。{RESET}\n")
else:
    print(f"\n  {RED}{BOLD}有 {failed} 项测试失败, 请检查。{RESET}\n")

sys.exit(0 if failed == 0 else 1)
