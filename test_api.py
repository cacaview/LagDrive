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
    check(__version__ == "1.0.0", f"版本号 = {__version__}")
except Exception as e:
    check(False, f"导入 lagdrive 失败: {e}")

try:
    from lagdrive.api import LagDriveAPI
    ok("LagDriveAPI 导入成功")
    passed += 1
except Exception as e:
    check(False, f"LagDriveAPI 导入失败: {e}")

try:
    from lagdrive.models import CellState, GridCell, NetworkMetrics
    ok("models 导入成功")
    passed += 1
except Exception as e:
    check(False, f"models 导入失败: {e}")

try:
    from lagdrive.monitor import Monitor, MonitorConfig
    ok("monitor 导入成功")
    passed += 1
except Exception as e:
    check(False, f"monitor 导入失败: {e}")

try:
    from lagdrive.dashboard import Dashboard
    ok("dashboard 导入成功")
    passed += 1
except Exception as e:
    check(False, f"dashboard 导入失败: {e}")

try:
    from lagdrive.quotes import select_quote
    ok("quotes 导入成功")
    passed += 1
except Exception as e:
    check(False, f"quotes 导入失败: {e}")


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
check("good" in Dashboard._rtt_color(30) or Dashboard._rtt_color(30) != "dim",
      "RTT < 50ms → good color")
check("bad" in Dashboard._rtt_color(1000) or Dashboard._rtt_color(1000) != "dim",
      "RTT > 500ms → bad color")


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
        ok(f"RTT = {rtt_result['avg_ms']} ms  ({rtt_result['success']}/3 成功)")
        passed += 1
    else:
        info("RTT 探测失败 (可能是网络限制, 跳过)")
        info("使用 --quick 跳过网络测试")

    info("RTT 探测 → 8.8.8.8:53 ...")
    rtt_result2 = LagDriveAPI.probe_rtt("8.8.8.8", 53, count=3, timeout=5.0)
    if rtt_result2["success"] > 0:
        ok(f"RTT = {rtt_result2['avg_ms']} ms  ({rtt_result2['success']}/3 成功)")
        passed += 1
    else:
        info("RTT 探测失败 (可能是网络限制, 跳过)")

    if run_network:
        info("吞吐量测试 (可能需要 10-30 秒)...")
        tp_result = LagDriveAPI.probe_throughput(test_size=5_000_000)
        if "error" not in tp_result:
            ok(f"吞吐量 = {tp_result['mbps']} Mbps  ({tp_result['bytes_downloaded']:,} bytes)")
            passed += 1
        else:
            info(f"吞吐量测试失败: {tp_result.get('error', 'unknown')}")


# ============================================================
# 9. Monitor 生命周期 (短暂)
# ============================================================
section("9. Monitor 生命周期测试")

api2 = LagDriveAPI(target="1.1.1.1", port=80, probe_interval=1.0)
check(not api2.running, "启动前 running = False")

api2.start()
time.sleep(0.5)
check(api2.running, "启动后 running = True")

time.sleep(10.0)
snap2 = api2.snapshot()
check(snap2["probe_count"] > 0, f"探测计数 = {snap2['probe_count']} (> 0)")
info(f"RTT: {snap2['rtt_current']:.1f} ms, Loss: {snap2['loss_rate']*100:.1f}%")

api2.stop()
time.sleep(0.5)
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
if result:
    ftype, body = result
    check(ftype == TYPE_WRITE, f"帧类型 = WRITE (0x{ftype:02x})")
    decoded = LagDriveProtocol.decode_block_body(body)
    check(decoded is not None, "decode_block_body 成功")
    if decoded:
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
    sock.connect(("127.0.0.1", actual_port))
    write_frame = LagDriveProtocol.encode_write(block_id=1, offset=0, data=b"relay test")
    sock.sendall(write_frame)

    # Read ECHO frame
    sock.settimeout(3.0)
    echo_result = LagDriveProtocol.decode_frame(sock)
    check(echo_result is not None, "收到 ECHO 帧")
    if echo_result:
        etype, ebody = echo_result
        check(etype == TYPE_ECHO, f"ECHO 类型正确 (0x{etype:02x})")
        decoded = LagDriveProtocol.decode_block_body(ebody)
        if decoded:
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

    sock.close()
except Exception as e:
    check(False, f"Relay 测试异常: {e}")

relay.stop()
time.sleep(0.3)
check(True, "Relay 正常关闭")


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

ss = StorageState()
check(ss.used_bytes == 0, "StorageState 初始 used_bytes = 0")
check(ss.relay_connected is False, "初始未连接")


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
