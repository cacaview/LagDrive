"""Rich-based DiskGenius-style terminal dashboard."""

from time import monotonic

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import CellState, GridCell, NetworkMetrics

# DiskGenius-inspired color palette
STYLES = {
    "title":          "bold white",
    "header_border":  "#2E86C1",
    "active_cell":    "bold #3498DB",
    "free_cell":      "#515A5A",
    "error_cell":     "bold #E74C3C",
    "stored_cell":    "bold #2ECC71",
    "stat_label":     "#95A5A6",
    "stat_value":     "bold white",
    "stat_good":      "bold #2ECC71",
    "stat_warn":      "bold #F39C12",
    "stat_bad":       "bold #E74C3C",
    "stat_unit":      "#7F8C8D",
    "quote":          "dim italic #F1C40F",
    "panel_border":   "#2E86C1",
}


class Dashboard:
    """DiskGenius-style terminal UI built on Rich."""

    def __init__(self) -> None:
        self._console = Console()
        self._live: Live | None = None
        self._grid: list[list[GridCell]] = []
        self._metrics = NetworkMetrics()
        self._quote: str = ""
        self._storage_state: dict | None = None
        self._status_msg: str = ""
        self._status_time: float = 0.0

    # --- Public API ---

    def start(self) -> None:
        """Enter live display mode."""
        self._live = Live(
            self._build_layout(),
            console=self._console,
            refresh_per_second=4,
            screen=True,
        )
        self._live.start()

    def stop(self) -> None:
        """Exit live display and show final state."""
        if self._live:
            self._live.stop()
            self._live = None
        self._console.print(self._build_final_panel())

    def update(
        self,
        metrics: NetworkMetrics | None = None,
        grid: list[list[GridCell]] | None = None,
        quote: str | None = None,
        storage_state: dict | None = None,
        status_msg: str | None = None,
    ) -> None:
        """Push new state to the live display."""
        if metrics is not None:
            self._metrics = metrics
        if grid is not None:
            self._grid = grid
        if quote is not None:
            self._quote = quote
        if storage_state is not None:
            self._storage_state = storage_state
        if status_msg is not None:
            self._status_msg = status_msg
            self._status_time = monotonic()
        if self._live:
            self._live.update(self._build_layout())

    # --- Layout assembly ---

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header",  size=13),
            Layout(name="body"),
            Layout(name="footer",  size=5),
            Layout(name="command", size=4),
        )
        layout["body"].split_row(
            Layout(name="left",  ratio=2),
            Layout(name="right", ratio=3),
        )
        storage_size = 8 if self._storage_state is not None else 3
        layout["header"].update(self._build_header())
        layout["left"].update(self._build_cluster_panel())
        layout["right"].split_column(
            Layout(name="info",    size=3),
            Layout(name="stats"),
            Layout(name="storage", size=storage_size),
        )
        layout["info"].update(self._build_info_panel())
        layout["stats"].update(self._build_perf_panel())
        layout["storage"].update(self._build_storage_panel())
        layout["footer"].update(self._build_quote_panel())
        layout["command"].update(self._build_command_panel())
        return layout

    # --- Header ---

    def _build_header(self) -> Panel:
        art = [
            "      ___       ___           ___           ___           ___                       ___           ___     ",
            "     /\\__\\     /\\  \\         /\\  \\         /\\  \\         /\\  \\          ___        /\\__\\         /\\  \\    ",
            "    /:/  /    /::\\  \\       /::\\  \\       /::\\  \\       /::\\  \\        /\\  \\      /:/  /        /::\\  \\   ",
            "   /:/  /    /:/\\:\\  \\     /:/\\:\\  \\     /:/\\:\\  \\     /:/\\:\\  \\       \\:\\  \\    /:/  /        /:/\\:\\  \\  ",
            "  /:/  /    /::\\~\\:\\  \\   /:/  \\:\\  \\   /:/  \\:\\__\\   /::\\~\\:\\  \\      /::\\__\\  /:/__/  ___   /::\\~\\:\\  \\ ",
            " /:/__/    /:/\\:\\ \\:\\__\\ /:/__/_\\:\\__\\ /:/__/ \\:|__| /:/\\:\\ \\:\\__\\  __/:/\\/__/  |:|  | /\\__\\ /:/\\:\\ \\:\\__\\",
            " \\:\\  \\    \\/__\\:\\/:/  / \\:\\  /\\ \\/__/ \\:\\  \\ /:/  / \\/_|::\\/:/  / /\\/:/  /     |:|  |/:/  / \\:\\~\\:\\ \\/__/",
            "  \\:\\  \\        \\::/  /   \\:\\ \\:\\__\\    \\:\\  /:/  /     |:|::/  /  \\::/__/      |:|__/:/  /   \\:\\ \\:\\__\\  ",
            "   \\:\\  \\       /:/  /     \\:\\/:/  /     \\:\\/:/  /      |:|\\/__    \\:\\__\\       \\::::/__/     \\:\\ \\/__/  ",
            "    \\:\\__\\     /:/  /       \\::/  /       \\::/__/       |:|  |       \\/__/        ~~~~          \\:\\__\\    ",
            "     \\/__/     \\/__/         \\/__/         ~~            \\|__|                                   \\/__/    ",
        ]
        title = Text()
        for line in art:
            title.append(line + "\n", "bold white")
        return Panel(title, style=f"on {STYLES['header_border']}", height=13)

    # --- Cluster grid (10x10) ---

    def _build_cluster_panel(self) -> Panel:
        if not self._grid:
            return Panel(
                Text("等待初始化...", style="dim"),
                title="[bold]簇阵列视图[/bold]",
                border_style=STYLES["panel_border"],
            )

        table = Table(
            show_header=False,
            show_edge=False,
            pad_edge=False,
            padding=0,
            box=None,
        )
        for _ in self._grid[0]:
            table.add_column(width=6, justify="center")

        for row in self._grid:
            cells = []
            for cell in row:
                t = Text()
                if cell.state == CellState.ACTIVE:
                    t.append(" [", "default")
                    t.append("·", STYLES["active_cell"])
                    t.append("] ", "default")
                elif cell.state == CellState.ERROR:
                    t.append(" [", "default")
                    t.append("!", STYLES["error_cell"])
                    t.append("] ", "default")
                elif cell.state == CellState.STORED:
                    t.append(" [", "default")
                    t.append("S", STYLES["stored_cell"])
                    t.append("] ", "default")
                else:
                    t.append(" [ ] ", STYLES["free_cell"])
                cells.append(t)
            table.add_row(*cells)

        return Panel(
            table,
            title="[bold]簇阵列视图[/bold]",
            subtitle="[dim]S=Stored  ·=Active  ( )=Free  !=Error[/dim]",
            border_style=STYLES["panel_border"],
        )

    # --- Disk info panel ---

    def _build_info_panel(self) -> Panel:
        m = self._metrics
        cap = m.capacity
        cap_str, cap_unit = self._format_bytes(cap)

        color = STYLES["stat_good"] if cap > 1_000_000 else (
            STYLES["stat_warn"] if cap > 10_000 else STYLES["stat_value"]
        )

        t = Text()
        t.append("  L: ", "bold")
        t.append("LagDrive ", "bold #2E86C1")
        t.append("| ", "dim")
        t.append("Capacity: ", STYLES["stat_label"])
        t.append(f"{cap_str} {cap_unit}", color)

        return Panel(t, border_style=STYLES["panel_border"], height=3)

    # --- Performance panel ---

    def _build_perf_panel(self) -> Panel:
        m = self._metrics

        table = Table(
            show_header=True,
            header_style="bold #2E86C1",
            box=None,
            pad_edge=False,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("指标", style=STYLES["stat_label"], ratio=2)
        table.add_column("当前值", justify="right", ratio=1)
        table.add_column("平均值", justify="right", ratio=1)

        # Seek Time (RTT)
        rtt_color = self._rtt_color(m.rtt_current)
        table.add_row(
            "Seek Time (RTT)",
            Text(f"{m.rtt_current:.0f} ms", style=rtt_color),
            Text(f"{m.rtt_avg:.0f} ms", style=self._rtt_color(m.rtt_avg)),
        )

        # Sequential Read (throughput)
        tp_color = STYLES["stat_good"] if m.throughput_current > 10 else STYLES["stat_warn"]
        table.add_row(
            "Sequential Read",
            Text(f"{m.throughput_current:.1f} Mbps", style=tp_color),
            Text(f"{m.throughput_avg:.1f} Mbps", style=tp_color),
        )

        # Bad Sectors (packet loss)
        loss_color = STYLES["stat_bad"] if m.loss_rate > 0.05 else STYLES["stat_value"]
        table.add_row(
            "Bad Sectors (Loss)",
            Text(f"{m.loss_rate * 100:.1f}%", style=loss_color),
            Text("-", style="dim"),
        )

        # Data in Transit
        dit = m.data_in_transit
        dit_str, dit_unit = self._format_bytes(dit)
        table.add_row(
            "Data in Transit",
            Text(f"{dit_str} {dit_unit}", style="bold #3498DB"),
            Text("-", style="dim"),
        )

        # Total I/O
        dl_str, dl_unit = self._format_bytes(m.total_downloaded)
        ul_str, ul_unit = self._format_bytes(m.total_uploaded)
        table.add_row(
            "Total I/O (Down/Up)",
            Text(f"{dl_str} {dl_unit}", style="bold #9B59B6"),
            Text(f"{ul_str} {ul_unit}", style="bold #9B59B6"),
        )

        return Panel(
            table,
            title="[bold]性能面板[/bold]",
            border_style=STYLES["panel_border"],
        )

    # --- Storage panel ---

    def _build_storage_panel(self) -> Panel:
        ss = self._storage_state
        if ss is None:
            return Panel(
                Text("  存储未启用", style="dim"),
                title="[bold]存储状态[/bold]",
                border_style="#9B59B6",
            )

        used = ss.get("used_bytes", 0)
        cap = ss.get("capacity_bytes", 0)
        used_str, used_unit = self._format_bytes(used)
        cap_str, cap_unit = self._format_bytes(cap)
        total = ss.get("total_blocks", 0)
        confirmed = ss.get("confirmed_blocks", 0)
        expired = ss.get("expired_blocks", 0)
        connected = ss.get("relay_connected", False)

        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 1), expand=True)
        table.add_column(style=STYLES["stat_label"], ratio=1)
        table.add_column(justify="right", ratio=1)

        conn_style = STYLES["stat_good"] if connected else STYLES["stat_bad"]
        conn_text = "Connected" if connected else "Disconnected"

        table.add_row(
            "Used / Capacity",
            Text(f"{used_str} {used_unit} / {cap_str} {cap_unit}", style=STYLES["stat_value"]),
        )
        table.add_row(
            "Blocks",
            Text(f"{total}  (confirmed: {confirmed}, expired: {expired})", style=STYLES["stat_value"]),
        )
        table.add_row(
            "Relay",
            Text(conn_text, style=conn_style),
        )

        return Panel(
            table,
            title="[bold]存储状态[/bold]",
            border_style="#9B59B6",
        )

    # --- Sarcastic quote panel ---

    def _build_quote_panel(self) -> Panel:
        t = Text()
        if self._quote:
            t.append(f"  {self._quote}", STYLES["quote"])
        else:
            t.append("  正在初始化讽刺引擎...", "dim")
        return Panel(
            t,
            title="[bold]系统通知[/bold]",
            border_style="#F39C12",
            height=3,
        )

    # --- Command bar ---

    def _build_command_panel(self) -> Panel:
        storage_on = self._storage_state is not None
        s_label = "[S]断开存储" if storage_on else "[S]启用存储"
        s_style = "bold #E74C3C" if storage_on else "bold #2ECC71"

        keys = Text()
        keys.append(f"  {s_label}", s_style)
        keys.append("  [W]写入", "bold #3498DB")
        keys.append("  [R]读取", "bold #3498DB")
        keys.append("  [I]状态", "bold #3498DB")
        keys.append("  [C]清除", "bold #3498DB")
        keys.append("  | ", "dim")
        keys.append("[P]RTT", "bold #F39C12")
        keys.append("  [T]吞吐", "bold #F39C12")
        keys.append("  [A]诊断", "bold #F39C12")
        keys.append("  [B]BDP", "bold #F39C12")
        keys.append("  | ", "dim")
        keys.append("[Q]退出", "bold #E74C3C")
        # Status message (expires after 5 seconds)
        msg = ""
        if self._status_msg and (monotonic() - self._status_time < 5.0):
            msg = self._status_msg
        t_line2 = Text()
        if msg:
            t_line2.append(f"  > {msg}", "bold #2ECC71")
        else:
            t_line2.append("  > ", "dim")
        content = Text()
        content.append_text(keys)
        content.append("\n")
        content.append_text(t_line2)
        return Panel(content, border_style="#34495E", height=4)

    # --- Final state (after stop) ---

    def _build_final_panel(self) -> Panel:
        m = self._metrics
        cap_str, cap_unit = self._format_bytes(m.capacity)
        dl_str, dl_unit = self._format_bytes(m.total_downloaded)

        t = Text()
        t.append("\n  LagDrive 会话已结束\n\n", "bold white")
        t.append(f"  最终虚拟容量:  {cap_str} {cap_unit}\n", STYLES["stat_value"])
        t.append(f"  平均寻道时间:  {m.rtt_avg:.0f} ms\n", STYLES["stat_value"])
        t.append(f"  总数据传输:    {dl_str} {dl_unit}\n", STYLES["stat_value"])
        t.append(f"  丢包率:        {m.loss_rate * 100:.1f}%\n", STYLES["stat_value"])
        t.append("\n  所有数据已清空。就像你的带宽一样——从未真正存在过。\n", "dim italic")
        return Panel(t, border_style=STYLES["panel_border"])

    # --- Helpers ---

    @staticmethod
    def _format_bytes(value: float) -> tuple[str, str]:
        """Format bytes into a human-readable (value, unit) pair."""
        if value <= 0:
            return "0.0", "B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        v = float(value)
        while v >= 1024 and idx < len(units) - 1:
            v /= 1024
            idx += 1
        return f"{v:.1f}", units[idx]

    @staticmethod
    def _rtt_color(rtt: float) -> str:
        if rtt <= 0:
            return "dim"
        if rtt < 50:
            return STYLES["stat_good"]
        if rtt < 200:
            return STYLES["stat_value"]
        if rtt < 500:
            return STYLES["stat_warn"]
        return STYLES["stat_bad"]
