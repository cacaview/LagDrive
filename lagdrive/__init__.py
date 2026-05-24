"""
LagDrive — 将网络延迟模拟成虚拟硬盘的基准测试工具。

基于 BDP (Bandwidth-Delay Product) 原理：
    Capacity(bytes) = Bandwidth(bps) × RTT(s) / 8

延迟越高，链路中同时存在的比特流越多，理论"网线容量"越大。
"""

__version__ = "1.0.0"

import argparse
import signal
import sys
import threading
import time
from time import monotonic

from rich.console import Console

from .api import LagDriveAPI
from .dashboard import Dashboard
from .monitor import MonitorConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lagdrive",
        description="LagDrive — 网络延迟就是你的硬盘容量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  lagdrive                          # 默认探测 1.1.1.1
  lagdrive -t 8.8.8.8              # 指定目标
  lagdrive --probe-rtt              # 单次 RTT 探测 (API 调试)
  lagdrive --probe-throughput       # 单次吞吐量测试 (API 调试)
  lagdrive --probe-all              # 完整诊断 (API 调试)
  lagdrive --snapshot               # JSON 格式输出状态 (API 调试)
        """,
    )
    parser.add_argument("-t", "--target", default="1.1.1.1",
                        help="探测目标主机 (default: 1.1.1.1)")
    parser.add_argument("-p", "--port", type=int, default=80,
                        help="探测目标端口 (default: 80)")
    parser.add_argument("--probe-interval", type=float, default=2.0,
                        help="RTT 探测间隔/秒 (default: 2.0)")

    # API debug commands
    api_group = parser.add_argument_group("API 调试命令")
    api_group.add_argument("--probe-rtt", action="store_true",
                           help="执行单次 RTT 探测并输出结果")
    api_group.add_argument("--probe-throughput", action="store_true",
                           help="执行单次吞吐量测试并输出结果")
    api_group.add_argument("--probe-all", action="store_true",
                           help="执行完整诊断 (RTT + 吞吐量 + BDP)")
    api_group.add_argument("--snapshot", action="store_true",
                           help="启动监控, 定期输出 JSON 状态快照")
    api_group.add_argument("--bdp", nargs=2, type=float, metavar=("RTT", "MBPS"),
                           help="计算指定 RTT(ms) 和带宽(Mbps) 的 BDP 容量")

    # Storage commands
    storage_group = parser.add_argument_group("存储命令")
    storage_group.add_argument("--relay", action="store_true",
                               help="启动 Echo Relay 服务器")
    storage_group.add_argument("--relay-host", default="127.0.0.1",
                               help="Echo Relay 地址 (default: 127.0.0.1)")
    storage_group.add_argument("--relay-port", type=int, default=9527,
                               help="Echo Relay 端口 (default: 9527)")
    storage_group.add_argument("--store", type=str, metavar="DATA",
                               help="写入数据到网络存储")
    storage_group.add_argument("--read", nargs=2, type=int, metavar=("OFFSET", "LENGTH"),
                               help="从网络存储读取数据")
    storage_group.add_argument("--storage-info", action="store_true",
                               help="显示存储状态")
    storage_group.add_argument("--storage", action="store_true",
                               help="启用存储模式 (需要运行中的 Relay)")

    return parser


def _print_json(data: dict) -> None:
    import json
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_probe_rtt(target: str, port: int) -> None:
    console = Console()
    console.print(f"\n[bold]RTT 探测 → {target}:{port}[/bold]\n")
    result = LagDriveAPI.probe_rtt(target, port)
    console.print(f"  目标:     {result['target']}")
    console.print(f"  样本:     {result['samples']}")
    console.print(f"  平均 RTT: [bold]{result['avg_ms']} ms[/bold]")
    console.print(f"  最小:     {result['min_ms']} ms")
    console.print(f"  最大:     {result['max_ms']} ms")
    console.print(f"  成功/失败: {result['success']}/{result['fail']}")
    quote = LagDriveAPI.get_quote(rtt_avg=result["avg_ms"])
    console.print(f"\n  [dim italic]{quote}[/dim italic]\n")


def _cmd_probe_throughput() -> None:
    console = Console()
    console.print("\n[bold]吞吐量测试[/bold]\n")
    result = LagDriveAPI.probe_throughput()
    console.print(f"  下载量:   {result['bytes_downloaded']:,} bytes")
    console.print(f"  耗时:     {result['elapsed_s']} s")
    console.print(f"  带宽:     [bold]{result['mbps']} Mbps[/bold]")
    if "error" in result:
        console.print(f"  错误:     [red]{result['error']}[/red]")
    console.print()


def _cmd_probe_all(target: str, port: int) -> None:
    console = Console()
    console.print(f"\n[bold]完整诊断 → {target}:{port}[/bold]\n")

    console.print("[1/3] RTT 探测...")
    rtt = LagDriveAPI.probe_rtt(target, port)
    console.print(f"      平均 RTT: {rtt['avg_ms']} ms  ({rtt['success']}/{rtt['success']+rtt['fail']} 成功)")

    console.print("[2/3] 吞吐量测试...")
    tp = LagDriveAPI.probe_throughput()
    console.print(f"      带宽: {tp['mbps']} Mbps")

    console.print("[3/3] BDP 计算...")
    bdp = LagDriveAPI.compute_bdp(rtt["avg_ms"], tp["mbps"])
    console.print(f"      虚拟容量: [bold]{bdp['capacity_human']}[/bold]")

    console.print(f"\n  [dim italic]{LagDriveAPI.get_quote(rtt['avg_ms'], 0, tp['bytes_downloaded'], tp['mbps'], bdp['capacity_bytes'])}[/dim italic]\n")


def _cmd_bdp(rtt: float, mbps: float) -> None:
    result = LagDriveAPI.compute_bdp(rtt, mbps)
    _print_json(result)


def _cmd_snapshot(target: str, port: int, interval: float) -> None:
    console = Console()
    api = LagDriveAPI(target=target, port=port, probe_interval=interval)
    api.start()
    console.print(f"[bold]LagDrive Snapshot 模式[/bold] → {target}:{port}  (Ctrl+C 退出)\n")
    try:
        while True:
            time.sleep(interval)
            snap = api.snapshot()
            _print_json(snap)
            print()
    except KeyboardInterrupt:
        api.stop()
        console.print("\n已停止。")


def _cmd_relay(host: str, port: int) -> None:
    """Start Echo Relay server (blocking)."""
    from .relay import EchoRelay
    console = Console()
    console.print(f"\n[bold]LagDrive Echo Relay[/bold]")
    console.print(f"  监听: {host}:{port}")
    console.print(f"  [dim]按 Ctrl+C 停止...[/dim]\n")
    relay = EchoRelay(host, port)
    relay.serve_forever()
    console.print("\n已停止。")


def _cmd_store(relay_host: str, relay_port: int, data: str) -> None:
    """Write data to network storage."""
    console = Console()
    api = LagDriveAPI(
        target=relay_host, port=80,
        storage_enabled=True,
        relay_host=relay_host, relay_port=relay_port,
    )
    api.start()
    time.sleep(1.0)
    result = api.write(data.encode("utf-8"))
    console.print(f"\n[bold]写入结果[/bold]")
    _print_json(result)
    info = api.storage_info()
    if info:
        console.print(f"\n[bold]存储状态[/bold]")
        _print_json(info)
    api.stop()


def _cmd_read(relay_host: str, relay_port: int, offset: int, length: int) -> None:
    """Read data from network storage."""
    console = Console()
    api = LagDriveAPI(
        target=relay_host, port=80,
        storage_enabled=True,
        relay_host=relay_host, relay_port=relay_port,
    )
    api.start()
    time.sleep(1.0)
    data = api.read(offset, length)
    console.print(f"\n[bold]读取结果[/bold] (offset={offset}, length={length})")
    try:
        text = data.decode("utf-8")
        console.print(f"  文本: {text}")
    except UnicodeDecodeError:
        console.print(f"  Hex:  {data.hex()}")
    console.print(f"  原始: {data!r}")
    api.stop()


def _cmd_storage_info(relay_host: str, relay_port: int) -> None:
    """Show storage status."""
    console = Console()
    api = LagDriveAPI(
        target=relay_host, port=80,
        storage_enabled=True,
        relay_host=relay_host, relay_port=relay_port,
    )
    api.start()
    time.sleep(1.0)
    info = api.storage_info()
    if info:
        _print_json(info)
    else:
        console.print("[red]存储未启用[/red]")
    api.stop()


def _read_key() -> str | None:
    """Non-blocking single key read. Returns None if no key pressed."""
    if sys.platform == "win32":
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            return ch
        return None
    else:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            return ch
        return None


def _handle_write(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Pause Live, prompt for data, write to storage, resume."""
    if api._monitor._storage is None:
        dashboard.update(status_msg="存储未启用")
        return
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        data = console.input("\n[bold cyan]输入要写入的数据:[/bold cyan] ")
        if not data:
            dashboard.update(status_msg="已取消")
            return
        result = api.write(data.encode("utf-8"))
        msg = f"写入成功 {result['bytes_written']} bytes ({result['blocks_written']} blocks)"
        console.print(f"  [green]{msg}[/green]")
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(3.0)
        dashboard.update(status_msg=msg)
    except (EOFError, KeyboardInterrupt):
        dashboard.update(status_msg="已取消")
    if dashboard._live:
        dashboard._live.start()


def _handle_read(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Pause Live, prompt for offset/length, read from storage, resume."""
    if api._monitor._storage is None:
        dashboard.update(status_msg="存储未启用")
        return
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        off_str = console.input("\n[bold cyan]Offset:[/bold cyan] ")
        len_str = console.input("[bold cyan]Length:[/bold cyan] ")
        offset = int(off_str)
        length = int(len_str)
        data = api.read(offset, length)
        try:
            text = data.decode("utf-8")
            console.print(f"  [green]文本: {text}[/green]")
        except UnicodeDecodeError:
            console.print(f"  [yellow]Hex: {data.hex()}[/yellow]")
        console.print(f"  [dim]原始: {data!r}[/dim]")
        msg = f"读取完成 {length} bytes"
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(3.0)
        dashboard.update(status_msg=msg)
    except (EOFError, KeyboardInterrupt, ValueError):
        dashboard.update(status_msg="已取消")
    if dashboard._live:
        dashboard._live.start()


def _handle_info(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Show storage info in the command bar."""
    info = api.storage_info()
    if info is None:
        dashboard.update(status_msg="存储未启用")
        return
    used = info["used_bytes"]
    cap = info["capacity_bytes"]
    blocks = info["total_blocks"]
    confirmed = info["confirmed_blocks"]
    expired = info["expired_blocks"]
    msg = f"Used: {used}/{cap} bytes  Blocks: {blocks} (confirmed: {confirmed}, expired: {expired})"
    dashboard.update(status_msg=msg)


def _handle_clear(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Clear all stored blocks."""
    result = api.clear_storage()
    if result.get("cleared"):
        dashboard.update(status_msg=f"已清除 {result['blocks_cleared']} 个 blocks")
    else:
        dashboard.update(status_msg="存储未启用")


def _handle_toggle_storage(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Enable or disable storage at runtime."""
    if api._monitor._storage is not None:
        result = api.disable_storage()
        dashboard.update(status_msg="存储已断开")
        return

    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        host = console.input("\n[bold cyan]Relay 地址[/bold cyan] [dim](默认 127.0.0.1):[/dim] ").strip()
        port_str = console.input("[bold cyan]Relay 端口[/bold cyan] [dim](默认 9527):[/dim] ").strip()
        host = host or "127.0.0.1"
        port = int(port_str) if port_str else 9527
        console.print(f"  正在连接 {host}:{port}...")
        result = api.enable_storage(host, port)
        if result.get("enabled"):
            console.print(f"  [green]存储已启用 → {result['relay']}[/green]")
            msg = f"存储已连接 {result['relay']}"
        else:
            console.print(f"  [red]连接失败: {result.get('error')}[/red]")
            msg = f"连接失败: {result.get('error')}"
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(5.0)
        dashboard.update(status_msg=msg)
    except (EOFError, KeyboardInterrupt, ValueError):
        dashboard.update(status_msg="已取消")
    if dashboard._live:
        dashboard._live.start()


def _handle_probe_rtt(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Run single RTT probe, show result."""
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        target = api._config.target
        port = api._config.port
        console.print(f"\n[bold]RTT 探测 → {target}:{port}[/bold]")
        result = LagDriveAPI.probe_rtt(target, port)
        console.print(f"  平均 RTT: [bold]{result['avg_ms']} ms[/bold]  ({result['success']}/{result['success']+result['fail']} 成功)")
        console.print(f"  样本: {result['samples']}")
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(10.0)
        dashboard.update(status_msg=f"RTT: {result['avg_ms']} ms ({result['success']}/{result['success']+result['fail']})")
    except Exception as e:
        dashboard.update(status_msg=f"RTT 探测失败: {e}")
    if dashboard._live:
        dashboard._live.start()


def _handle_probe_throughput(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Run throughput test, show result."""
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        console.print("\n[bold]吞吐量测试...[/bold]")
        result = LagDriveAPI.probe_throughput(test_size=5_000_000)
        if "error" in result:
            console.print(f"  [red]失败: {result['error']}[/red]")
            dashboard.update(status_msg="吞吐量测试失败")
        else:
            console.print(f"  带宽: [bold]{result['mbps']} Mbps[/bold]  ({result['bytes_downloaded']:,} bytes)")
            console.print(f"  耗时: {result['elapsed_s']} s")
            dashboard.update(status_msg=f"带宽: {result['mbps']} Mbps")
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(10.0)
    except Exception as e:
        dashboard.update(status_msg=f"吞吐量测试失败: {e}")
    if dashboard._live:
        dashboard._live.start()


def _handle_probe_all(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """Run full diagnosis: RTT + throughput + BDP."""
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        target = api._config.target
        port = api._config.port
        console.print(f"\n[bold]完整诊断 → {target}:{port}[/bold]\n")
        console.print("[1/3] RTT 探测...")
        rtt = LagDriveAPI.probe_rtt(target, port)
        console.print(f"      平均 RTT: {rtt['avg_ms']} ms  ({rtt['success']}/{rtt['success']+rtt['fail']} 成功)")
        console.print("[2/3] 吞吐量测试...")
        tp = LagDriveAPI.probe_throughput(test_size=5_000_000)
        mbps = tp.get("mbps", 0)
        console.print(f"      带宽: {mbps} Mbps")
        console.print("[3/3] BDP 计算...")
        bdp = LagDriveAPI.compute_bdp(rtt["avg_ms"], mbps)
        console.print(f"      虚拟容量: [bold]{bdp['capacity_human']}[/bold]")
        quote = LagDriveAPI.get_quote(rtt["avg_ms"], 0, tp.get("bytes_downloaded", 0), mbps, bdp["capacity_bytes"])
        console.print(f"\n  [dim italic]{quote}[/dim italic]")
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(15.0)
        dashboard.update(status_msg=f"RTT: {rtt['avg_ms']}ms | 带宽: {mbps}Mbps | 容量: {bdp['capacity_human']}")
    except Exception as e:
        dashboard.update(status_msg=f"诊断失败: {e}")
    if dashboard._live:
        dashboard._live.start()


def _handle_bdp(dashboard: Dashboard, api: LagDriveAPI) -> None:
    """BDP calculator."""
    if dashboard._live:
        dashboard._live.stop()
    console = Console()
    try:
        rtt_str = console.input("\n[bold cyan]RTT (ms):[/bold cyan] ")
        mbps_str = console.input("[bold cyan]带宽 (Mbps):[/bold cyan] ")
        rtt = float(rtt_str)
        mbps = float(mbps_str)
        bdp = LagDriveAPI.compute_bdp(rtt, mbps)
        console.print(f"\n  虚拟容量: [bold]{bdp['capacity_human']}[/bold]  ({bdp['capacity_bytes']:.0f} bytes)")
        console.print("  [dim]按任意键继续...[/dim]")
        _read_key_or_wait(10.0)
        dashboard.update(status_msg=f"BDP: {bdp['capacity_human']}")
    except (ValueError, EOFError, KeyboardInterrupt):
        dashboard.update(status_msg="已取消")
    if dashboard._live:
        dashboard._live.start()


def _read_key_or_wait(timeout: float) -> None:
    """Wait for a keypress or timeout."""
    t0 = monotonic()
    while monotonic() - t0 < timeout:
        if _read_key() is not None:
            return
        time.sleep(0.05)


def _run_dashboard(target: str, port: int, probe_interval: float,
                   relay_host: str = "127.0.0.1", relay_port: int = 9527,
                   storage_enabled: bool = False) -> None:
    console = Console()
    dashboard = Dashboard()
    api = LagDriveAPI(
        target=target, port=port, probe_interval=probe_interval,
        relay_host=relay_host, relay_port=relay_port,
        storage_enabled=storage_enabled,
    )

    def poll_loop():
        """Poll API snapshot and push to dashboard."""
        while api.running:
            time.sleep(0.5)
            snap = api.snapshot()
            from .models import NetworkMetrics
            m = NetworkMetrics()
            m.rtt_current = snap["rtt_current"]
            m.rtt_avg = snap["rtt_avg"]
            m.throughput_current = snap["throughput_current"]
            m.throughput_avg = snap["throughput_avg"]
            m.loss_rate = snap["loss_rate"]
            m.total_downloaded = snap["total_downloaded"]
            m.total_uploaded = snap["total_uploaded"]
            m.probe_count = snap["probe_count"]
            m.fail_count = snap["fail_count"]
            dashboard.update(
                metrics=m,
                grid=api._monitor.grid,
                quote=snap["quote"],
                storage_state=snap.get("storage"),
            )

    api.start()
    poller = threading.Thread(target=poll_loop, daemon=True)
    poller.start()

    try:
        dashboard.start()
        while True:
            key = _read_key()
            if key is not None:
                key = key.lower()
                if key == 'q':
                    break
                elif key == 'w':
                    _handle_write(dashboard, api)
                elif key == 'r':
                    _handle_read(dashboard, api)
                elif key == 'i':
                    _handle_info(dashboard, api)
                elif key == 'c':
                    _handle_clear(dashboard, api)
                elif key == 's':
                    _handle_toggle_storage(dashboard, api)
                elif key == 'p':
                    _handle_probe_rtt(dashboard, api)
                elif key == 't':
                    _handle_probe_throughput(dashboard, api)
                elif key == 'a':
                    _handle_probe_all(dashboard, api)
                elif key == 'b':
                    _handle_bdp(dashboard, api)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        api.stop()
        dashboard.stop()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Route to storage commands
    if args.relay:
        _cmd_relay(args.relay_host, args.relay_port)
        return
    if args.store:
        _cmd_store(args.relay_host, args.relay_port, args.store)
        return
    if args.read:
        _cmd_read(args.relay_host, args.relay_port, args.read[0], args.read[1])
        return
    if args.storage_info:
        _cmd_storage_info(args.relay_host, args.relay_port)
        return

    # Route to API debug commands
    if args.probe_rtt:
        _cmd_probe_rtt(args.target, args.port)
        return
    if args.probe_throughput:
        _cmd_probe_throughput()
        return
    if args.probe_all:
        _cmd_probe_all(args.target, args.port)
        return
    if args.bdp:
        _cmd_bdp(args.bdp[0], args.bdp[1])
        return
    if args.snapshot:
        _cmd_snapshot(args.target, args.port, args.probe_interval)
        return

    # Default: full dashboard
    _run_dashboard(args.target, args.port, args.probe_interval,
                   relay_host=args.relay_host, relay_port=args.relay_port,
                   storage_enabled=args.storage)


if __name__ == "__main__":
    main()
