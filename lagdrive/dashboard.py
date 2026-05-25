"""Rich-based DiskGenius-style terminal dashboard with enhanced TUI."""

from time import monotonic

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import ActivityEvent, ActivityEventType, CellState, GridCell, NetworkMetrics
from .quotes import select_exit_quote

# --- Theme definitions ---

THEMES = {
    "dark": {
        "name": "DiskGenius Dark",
        "title":          "bold white",
        "header_border":  "#2E86C1",
        "active_cell":    "bold #3498DB",
        "free_cell":      "#515A5A",
        "error_cell":     "bold #E74C3C",
        "stored_cell":    "bold #2ECC71",
        "stored_flash":   "bold #7DFFB3",
        "stat_label":     "#95A5A6",
        "stat_value":     "bold white",
        "stat_good":      "bold #2ECC71",
        "stat_warn":      "bold #F39C12",
        "stat_bad":       "bold #E74C3C",
        "stat_unit":      "#7F8C8D",
        "quote":          "dim italic #F1C40F",
        "panel_border":   "#2E86C1",
        "bar_good":       "#2ECC71",
        "bar_warn":       "#F39C12",
        "bar_bad":        "#E74C3C",
        "log_panel":      "#9B59B6",
        "accent":         "#9B59B6",
        "bg":             "",
    },
    "light": {
        "name": "Light Mode",
        "title":          "bold #2C3E50",
        "header_border":  "#3498DB",
        "active_cell":    "bold #2980B9",
        "free_cell":      "#BDC3C7",
        "error_cell":     "bold #C0392B",
        "stored_cell":    "bold #27AE60",
        "stored_flash":   "bold #1ABC9C",
        "stat_label":     "#7F8C8D",
        "stat_value":     "bold #2C3E50",
        "stat_good":      "bold #27AE60",
        "stat_warn":      "bold #E67E22",
        "stat_bad":       "bold #C0392B",
        "stat_unit":      "#95A5A6",
        "quote":          "italic #8E44AD",
        "panel_border":   "#3498DB",
        "bar_good":       "#27AE60",
        "bar_warn":       "#E67E22",
        "bar_bad":        "#C0392B",
        "log_panel":      "#8E44AD",
        "accent":         "#8E44AD",
        "bg":             "",
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "title":          "bold #FF00FF",
        "header_border":  "#00FFFF",
        "active_cell":    "bold #00FFFF",
        "free_cell":      "#333355",
        "error_cell":     "bold #FF0044",
        "stored_cell":    "bold #00FF88",
        "stored_flash":   "bold #FFFF00",
        "stat_label":     "#8888AA",
        "stat_value":     "bold #EEEEFF",
        "stat_good":      "bold #00FF88",
        "stat_warn":      "bold #FFAA00",
        "stat_bad":       "bold #FF0044",
        "stat_unit":      "#666688",
        "quote":          "italic #FF00FF",
        "panel_border":   "#00FFFF",
        "bar_good":       "#00FF88",
        "bar_warn":       "#FFAA00",
        "bar_bad":        "#FF0044",
        "log_panel":      "#FF00FF",
        "accent":         "#FF00FF",
        "bg":             "",
    },
}

THEME_ORDER = ["dark", "light", "cyberpunk"]

# Backward-compatible alias (used by tests)
STYLES = THEMES["dark"]

# Sparkline block chars (8 levels)
_SPARK_CHARS = " ▁▂▃▄▅▆▇█"

# Pulse state for active cells (alternates per tick)
_pulse_phase = 0


def _make_sparkline(data: list[float], width: int = 12) -> str:
    """Render a mini sparkline from data using Unicode block chars."""
    if not data or len(data) < 2:
        return ""
    # Take last `width` samples
    samples = data[-width:]
    mn = min(samples)
    mx = max(samples)
    rng = mx - mn
    if rng == 0:
        rng = 1.0
    chars = []
    for v in samples:
        idx = int((v - mn) / rng * 7)
        idx = max(0, min(7, idx))
        chars.append(_SPARK_CHARS[idx + 1])
    return "".join(chars)


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
        self._activity_events: list[dict] = []
        # Theme
        self._theme_idx = 0
        self._theme = THEMES["dark"]
        # Modal dialog state
        self._modal_active = False
        self._modal_content: Panel | None = None
        # Grid animation timestamps
        self._grid_prev_confirmed: int = 0
        self._newly_confirmed_until: float = 0.0
        # Terminal size detection
        self._term_width: int = 120
        self._term_height: int = 40
        self._compact: bool = False

    @property
    def _s(self) -> dict:
        """Shorthand for current theme styles."""
        return self._theme

    # --- Public API ---

    def start(self) -> None:
        """Enter live display mode."""
        self._update_term_size()
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

    def cycle_theme(self) -> str:
        """Cycle to next theme. Returns theme name."""
        self._theme_idx = (self._theme_idx + 1) % len(THEME_ORDER)
        key = THEME_ORDER[self._theme_idx]
        self._theme = THEMES[key]
        return self._theme["name"]

    def set_modal(self, panel: Panel | None) -> None:
        """Show/hide an inline modal dialog overlay."""
        self._modal_active = panel is not None
        self._modal_content = panel

    def prompt_inline(self, prompt: str, timeout: float = 30.0) -> str | None:
        """Show an inline text input prompt within the TUI.

        Returns the entered text, or None if cancelled (Escape).
        Uses character-by-character keyboard capture.
        """
        import sys
        buf = ""
        t0 = monotonic()

        def _read_char() -> str | None:
            if sys.platform == "win32":
                import msvcrt
                if msvcrt.kbhit():
                    return msvcrt.getwch()
            else:
                import select
                if select.select([sys.stdin], [], [], 0)[0]:
                    return sys.stdin.read(1)
            return None

        def _render():
            t = Text()
            t.append(f"  {prompt}\n", "bold cyan")
            t.append(f"  > {buf}_", "bold white")
            t.append("\n\n  ", "default")
            t.append("[Enter]确认  [Esc]取消", "dim")
            panel = Panel(t, border_style=self._s["accent"], height=7)
            self.set_modal(panel)
            if self._live:
                self._live.update(self._build_layout())

        _render()
        try:
            while monotonic() - t0 < timeout:
                ch = _read_char()
                if ch is None:
                    import time
                    time.sleep(0.03)
                    continue
                if ch == '\r' or ch == '\n':
                    self.set_modal(None)
                    return buf
                elif ch == '\x1b':  # Escape
                    self.set_modal(None)
                    return None
                elif ch == '\x03':  # Ctrl+C
                    self.set_modal(None)
                    return None
                elif ch == '\x08' or ch == '\x7f':  # Backspace
                    buf = buf[:-1]
                elif ch.isprintable():
                    buf += ch
                _render()
        except (EOFError, KeyboardInterrupt):
            pass
        self.set_modal(None)
        return None

    def update(
        self,
        metrics: NetworkMetrics | None = None,
        grid: list[list[GridCell | str]] | None = None,
        quote: str | None = None,
        storage_state: dict | None = None,
        status_msg: str | None = None,
        activity_events: list[dict] | None = None,
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
        if activity_events is not None:
            self._activity_events = activity_events
        self._update_term_size()
        if self._live:
            self._live.update(self._build_layout())

    # --- Terminal size detection ---

    def _update_term_size(self) -> None:
        try:
            size = self._console.size
            self._term_width = size.width
            self._term_height = size.height
        except Exception:
            self._term_width = 120
            self._term_height = 40
        self._compact = self._term_width < 100

    # --- Layout assembly ---

    def _build_layout(self) -> Layout:
        if self._compact:
            return self._build_compact_layout()

        ss = self._storage_state
        if ss is not None:
            relay_count = len(ss.get("relay_health", []))
            degraded_extra = 1 if ss.get("degraded") else 0
            storage_size = 8 + relay_count + degraded_extra
            info_size = 5
        else:
            storage_size = 3
            info_size = 3
        # stats panel: 6 data rows + 1 header + 2 borders + 1 padding = 10
        stats_size = 10

        layout = Layout()
        layout.split_column(
            Layout(name="header",  size=8),
            Layout(name="body"),
            Layout(name="footer",  size=3),
            Layout(name="command", size=4),
        )
        layout["body"].split_row(
            Layout(name="left",  ratio=2),
            Layout(name="right", ratio=3),
        )
        # Left: cluster fills entire column
        layout["left"].update(self._build_cluster_panel())
        # Right: info + stats fixed, log + storage split remaining equally
        layout["right"].split_column(
            Layout(name="info",    size=info_size),
            Layout(name="stats",   size=stats_size),
            Layout(name="log",     ratio=1),
            Layout(name="storage", ratio=1),
        )

        layout["header"].update(self._build_header())
        layout["info"].update(self._build_info_panel())
        layout["stats"].update(self._build_perf_panel())
        layout["log"].update(self._build_activity_log())
        layout["storage"].update(self._build_storage_panel())
        layout["footer"].update(self._build_quote_panel())
        layout["command"].update(self._build_command_panel())

        if self._modal_active and self._modal_content:
            layout["body"].update(self._modal_content)

        return layout

    def _build_compact_layout(self) -> Layout:
        """Compact layout for narrow terminals (<100 cols)."""
        layout = Layout()
        ss = self._storage_state
        storage_size = 5 if ss is not None else 3
        log_size = min(len(self._activity_events) + 3, 8) if self._activity_events else 3

        layout.split_column(
            Layout(name="info",    size=3),
            Layout(name="body"),
            Layout(name="log",     size=log_size),
            Layout(name="storage", size=storage_size),
            Layout(name="footer",  size=3),
            Layout(name="command", size=4),
        )
        layout["body"].split_row(
            Layout(name="left",  ratio=1),
            Layout(name="right", ratio=2),
        )
        layout["info"].update(self._build_info_panel())
        layout["left"].update(self._build_cluster_panel(grid_size=5))
        layout["right"].update(self._build_perf_panel())
        layout["log"].update(self._build_activity_log())
        layout["storage"].update(self._build_storage_panel())
        layout["footer"].update(self._build_quote_panel())
        layout["command"].update(self._build_command_panel())

        if self._modal_active and self._modal_content:
            layout["body"].update(self._modal_content)

        return layout

    # --- Header ---

    def _build_header(self) -> Panel:
        if self._compact:
            t = Text()
            t.append("  LagDrive", "bold #2E86C1")
            t.append(" v1.2 ", "dim")
            t.append("| ", "dim")
            t.append(self._theme["name"], "dim italic")
            return Panel(t, style=f"on {self._s['header_border']}", height=3)

        art = [
            " ██╗      █████╗  ██████╗ ██████╗ ██████╗ ██╗██╗   ██╗███████╗",
            " ██║     ██╔══██╗██╔════╝ ██╔══██╗██╔══██╗██║██║   ██║██╔════╝",
            " ██║     ███████║██║  ███╗██║  ██║██████╔╝██║██║   ██║█████╗  ",
            " ██║     ██╔══██║██║   ██║██║  ██║██╔══██╗██║╚██╗ ██╔╝██╔══╝  ",
            " ███████╗██║  ██║╚██████╔╝██████╔╝██║  ██║██║ ╚████╔╝ ███████╗",
            " ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝",
        ]
        title = Text()
        for line in art:
            title.append(line + "\n", self._s["title"])
        return Panel(title, style=f"on {self._s['header_border']}", height=8)

    # --- Cluster grid ---

    def _build_cluster_panel(self, grid_size: int = 0) -> Panel:
        grid = self._grid
        if not grid:
            return Panel(
                Text("等待初始化...", style="dim"),
                title="[bold]簇阵列视图[/bold]",
                border_style=self._s["panel_border"],
            )

        # Compact mode: show sub-grid
        if grid_size and grid_size < len(grid):
            grid = [row[:grid_size] for row in grid[:grid_size]]

        table = Table(
            show_header=False,
            show_edge=False,
            pad_edge=False,
            padding=0,
            box=None,
        )
        for _ in (grid[0] if grid else []):
            table.add_column(width=6, justify="center")

        now = monotonic()
        flash_active = now - self._newly_confirmed_until < 0 and self._newly_confirmed_until > 0

        for row in grid:
            cells = []
            for cell in row:
                state = cell.state if isinstance(cell, GridCell) else cell
                t = Text()
                if state == CellState.ACTIVE or state == "active":
                    # Pulse effect: alternate brightness
                    pulse = int(now * 3) % 2
                    style = self._s["active_cell"] if pulse else "#2471A3"
                    t.append(" [", "default")
                    t.append("·", style)
                    t.append("] ", "default")
                elif state == CellState.ERROR or state == "error":
                    t.append(" [", "default")
                    t.append("!", self._s["error_cell"])
                    t.append("] ", "default")
                elif state == CellState.STORED or state == "stored":
                    # Flash newly confirmed blocks
                    style = self._s["stored_flash"] if flash_active else self._s["stored_cell"]
                    t.append(" [", "default")
                    t.append("S", style)
                    t.append("] ", "default")
                else:
                    t.append(" [ ] ", self._s["free_cell"])
                cells.append(t)
            table.add_row(*cells)

        # Detect new confirmed blocks for flash effect
        ss = self._storage_state
        if ss:
            confirmed = ss.get("confirmed_blocks", 0)
            if confirmed > self._grid_prev_confirmed:
                self._newly_confirmed_until = now + 1.0
            self._grid_prev_confirmed = confirmed

        return Panel(
            table,
            title="[bold]簇阵列视图[/bold]",
            subtitle="[dim]S=Stored  ·=Active  ( )=Free  !=Error[/dim]",
            border_style=self._s["panel_border"],
        )

    # --- Info panel with capacity progress bar ---

    def _build_info_panel(self) -> Panel:
        m = self._metrics
        cap = m.capacity
        cap_str, cap_unit = self._format_bytes(cap)

        color = self._s["stat_good"] if cap > 1_000_000 else (
            self._s["stat_warn"] if cap > 10_000 else self._s["stat_value"]
        )

        # Capacity usage bar (storage mode)
        bar_line = Text()
        ss = self._storage_state
        if ss is not None:
            used = ss.get("used_bytes", 0)
            total = ss.get("capacity_bytes", 0)
            ratio = used / total if total > 0 else 0
            pct = ratio * 100
            bar_width = 30
            filled = int(ratio * bar_width)
            empty = bar_width - filled

            # Color: green < 60%, yellow < 85%, red >= 85%
            if ratio < 0.6:
                bar_color = self._s["bar_good"]
            elif ratio < 0.85:
                bar_color = self._s["bar_warn"]
            else:
                bar_color = self._s["bar_bad"]

            bar_line.append("  Usage: ", self._s["stat_label"])
            bar_line.append("█" * filled, bar_color)
            bar_line.append("░" * empty, "#333333")
            bar_line.append(f" {pct:.0f}%", bar_color)
            used_str, used_unit = self._format_bytes(used)
            bar_line.append(f"  ({used_str} {used_unit})", self._s["stat_unit"])

        lines = Text()
        lines.append("  L: ", "bold")
        lines.append("LagDrive ", "bold #2E86C1")
        lines.append("| ", "dim")
        lines.append("Capacity: ", self._s["stat_label"])
        lines.append(f"{cap_str} {cap_unit}", color)

        content = Group(lines, bar_line) if ss is not None else lines
        return Panel(content, border_style=self._s["panel_border"])

    # --- Performance panel with sparklines and I/O rate ---

    def _build_perf_panel(self) -> Panel:
        m = self._metrics

        table = Table(
            show_header=True,
            header_style=f"bold {self._s['header_border']}",
            box=None,
            pad_edge=False,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("指标", style=self._s["stat_label"], ratio=2)
        table.add_column("当前值", justify="right", ratio=1)
        table.add_column("平均值", justify="right", ratio=1)
        table.add_column("趋势", justify="left", ratio=1)

        # Seek Time (RTT)
        rtt_color = self._rtt_color(m.rtt_current)
        rtt_spark = _make_sparkline(m.rtt_samples, width=12)
        table.add_row(
            "Seek Time (RTT)",
            Text(f"{m.rtt_current:.0f} ms", style=rtt_color),
            Text(f"{m.rtt_avg:.0f} ms", style=self._rtt_color(m.rtt_avg)),
            Text(rtt_spark, style="bold #3498DB"),
        )

        # Sequential Read (throughput)
        tp_color = self._s["stat_good"] if m.throughput_current > 10 else self._s["stat_warn"]
        tp_spark = _make_sparkline(m.throughput_samples, width=12)
        table.add_row(
            "Sequential Read",
            Text(f"{m.throughput_current:.1f} Mbps", style=tp_color),
            Text(f"{m.throughput_avg:.1f} Mbps", style=tp_color),
            Text(tp_spark, style="bold #2ECC71"),
        )

        # Bad Sectors (packet loss)
        loss_color = self._s["stat_bad"] if m.loss_rate > 0.05 else self._s["stat_value"]
        loss_spark = _make_sparkline(m.loss_samples, width=12)
        table.add_row(
            "Bad Sectors (Loss)",
            Text(f"{m.loss_rate * 100:.1f}%", style=loss_color),
            Text("-", style="dim"),
            Text(loss_spark, style="bold #E74C3C"),
        )

        # Data in Transit
        dit = m.data_in_transit
        dit_str, dit_unit = self._format_bytes(dit)
        table.add_row(
            "Data in Transit",
            Text(f"{dit_str} {dit_unit}", style="bold #3498DB"),
            Text("-", style="dim"),
            Text(""),
        )

        # I/O Rate
        dl_rate_str = self._format_rate(m.download_rate)
        ul_rate_str = self._format_rate(m.upload_rate)
        table.add_row(
            "I/O Rate (D/U)",
            Text(f"↓ {dl_rate_str}", style="bold #9B59B6"),
            Text(f"↑ {ul_rate_str}", style="bold #9B59B6"),
            Text(""),
        )

        # Total I/O
        dl_str, dl_unit = self._format_bytes(m.total_downloaded)
        ul_str, ul_unit = self._format_bytes(m.total_uploaded)
        table.add_row(
            "Total I/O (D/U)",
            Text(f"{dl_str} {dl_unit}", style="bold #9B59B6"),
            Text(f"{ul_str} {ul_unit}", style="bold #9B59B6"),
            Text(""),
        )

        return Panel(
            table,
            title="[bold]性能面板[/bold]",
            border_style=self._s["panel_border"],
        )

    # --- Activity log panel ---

    def _build_activity_log(self) -> Panel:
        if not self._activity_events:
            return Panel(
                Text("  无活动记录", style="dim"),
                title="[bold]活动日志[/bold]",
                border_style=self._s["log_panel"],
            )

        # Show last 8 events in reverse chronological order
        recent = self._activity_events[-8:]
        recent.reverse()

        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 1), expand=True)
        table.add_column(width=10, style=self._s["stat_unit"])
        table.add_column(ratio=1)

        type_styles = {
            "write":   (self._s["stat_good"],  "↓ Write"),
            "confirm": (self._s["active_cell"], "✓ Echo"),
            "expire":  (self._s["stat_warn"],   "⏰ Expire"),
            "lost":    (self._s["stat_bad"],    "✗ Lost"),
            "clear":   (self._s["stat_warn"],   "⎚ Clear"),
        }

        for ev in recent:
            ev_type = ev.get("type", "unknown")
            ts = ev.get("time", 0)
            size = ev.get("size", 0)
            style, label = type_styles.get(ev_type, ("dim", ev_type))

            time_str = ""
            if ts > 0:
                import datetime
                time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")

            size_str = f" ({self._format_bytes(size)[0]} {self._format_bytes(size)[1]})" if size > 0 else ""

            table.add_row(
                Text(time_str, style=self._s["stat_unit"]),
                Text(f"{label}{size_str}", style=style),
            )

        return Panel(
            table,
            title="[bold]活动日志[/bold]",
            border_style=self._s["log_panel"],
        )

    # --- Storage panel with RAID topology ---

    def _build_storage_panel(self) -> Panel:
        ss = self._storage_state
        if ss is None:
            return Panel(
                Text("  存储未启用", style="dim"),
                title="[bold]存储状态[/bold]",
                border_style=self._s["accent"],
            )

        used = ss.get("used_bytes", 0)
        cap = ss.get("capacity_bytes", 0)
        used_str, used_unit = self._format_bytes(used)
        cap_str, cap_unit = self._format_bytes(cap)
        total = ss.get("total_blocks", 0)
        confirmed = ss.get("confirmed_blocks", 0)
        expired = ss.get("expired_blocks", 0)
        lost = ss.get("lost_bytes", 0)
        connected = ss.get("relay_connected", False)
        raid_mode = ss.get("raid_mode", "none")
        relay_count = ss.get("relay_count", 0)

        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 1), expand=True)
        table.add_column(style=self._s["stat_label"], ratio=1)
        table.add_column(justify="right", ratio=1)

        conn_style = self._s["stat_good"] if connected else self._s["stat_bad"]
        conn_text = "Connected" if connected else "Disconnected"

        # RAID mode label
        if raid_mode and raid_mode != "none":
            mode_labels = {
                "raid0":  "RAID 0 条带",
                "raid1":  "RAID 1 镜像",
                "raid5":  "RAID 5 校验",
                "raid10": "RAID 10 镜像条带",
            }
            mode_text = mode_labels.get(raid_mode, raid_mode.upper())
            table.add_row(
                "模式",
                Text(f"{mode_text}  ({relay_count} relays)", style=f"bold {self._s['accent']}"),
            )

        table.add_row(
            "Used / Capacity",
            Text(f"{used_str} {used_unit} / {cap_str} {cap_unit}", style=self._s["stat_value"]),
        )
        table.add_row(
            "Blocks",
            Text(f"{total}  (confirmed: {confirmed}, expired: {expired})", style=self._s["stat_value"]),
        )
        if lost > 0:
            lost_str, lost_unit = self._format_bytes(lost)
            table.add_row(
                "Lost",
                Text(f"{lost_str} {lost_unit}", style=self._s["stat_bad"]),
            )
        table.add_row(
            "Relay",
            Text(conn_text, style=conn_style),
        )

        # Per-relay health and RTT + topology
        relay_health = ss.get("relay_health", [])
        relay_rtt = ss.get("relay_rtt", [])
        if relay_health:
            # RAID topology visualization
            if len(relay_health) >= 2:
                topo = self._build_raid_topology(raid_mode, relay_health, relay_rtt)
                table.add_row("", Text(topo, style="dim"))

            for i, rh in enumerate(relay_health):
                addr = rh["address"]
                alive = rh["alive"]
                rstyle = self._s["stat_good"] if alive else self._s["stat_bad"]
                status = "OK" if alive else "DOWN"
                rtt_str = ""
                if i < len(relay_rtt) and relay_rtt[i]["avg_ms"] > 0:
                    rtt_str = f"  RTT:{relay_rtt[i]['avg_ms']:.0f}ms"
                table.add_row(
                    f"  Relay {i}",
                    Text(f"{addr} {status}{rtt_str}", style=rstyle),
                )

        if ss.get("degraded"):
            table.add_row(
                "",
                Text("DEGRADED MODE", style=f"bold {self._s['stat_bad']}"),
            )

        return Panel(
            table,
            title="[bold]存储状态[/bold]",
            border_style=self._s["accent"],
        )

    def _build_raid_topology(self, mode: str, health: list[dict], rtt: list[dict]) -> str:
        """Build ASCII RAID topology diagram."""
        n = len(health)
        statuses = []
        for i, h in enumerate(health):
            tag = "●" if h["alive"] else "○"
            rtt_val = ""
            if i < len(rtt) and rtt[i]["avg_ms"] > 0:
                rtt_val = f"{rtt[i]['avg_ms']:.0f}ms"
            statuses.append(f"R{i}{tag}{rtt_val}")

        if mode == "raid0":
            # Stripe: Client -> R0, R1, R2
            return f"  Client --┬-- {statuses[0]}\n" + \
                   "".join(f"         ├-- {s}\n" for s in statuses[1:-1]) + \
                   f"         └-- {statuses[-1]}"
        elif mode == "raid1":
            # Mirror: Client => all
            return f"  Client ==┬== {statuses[0]}\n" + \
                   "".join(f"         ├== {s}\n" for s in statuses[1:-1]) + \
                   f"         └== {statuses[-1]}"
        elif mode == "raid5":
            # Distributed parity
            return f"  Client --┬-- {statuses[0]} [data]\n" + \
                   "".join(f"         ├-- {s} [{'parity' if i == n - 1 else 'data'}]\n" for i, s in enumerate(statuses[1:-1], 1)) + \
                   f"         └-- {statuses[-1]} [{'data' if n > 2 else 'parity'}]"
        elif mode == "raid10":
            # Mirrored pairs
            pairs = []
            for i in range(0, n, 2):
                if i + 1 < n:
                    pairs.append(f"  [{statuses[i]}=={statuses[i+1]}]")
                else:
                    pairs.append(f"  [{statuses[i]}]")
            return "  Pairs: " + " + ".join(pairs)
        return ""

    # --- Sarcastic quote panel ---

    def _build_quote_panel(self) -> Panel:
        t = Text()
        if self._quote:
            t.append(f"  {self._quote}", self._s["quote"])
        else:
            t.append("  正在初始化讽刺引擎...", "dim")
        return Panel(
            t,
            title="[bold]系统通知[/bold]",
            border_style=self._s["stat_warn"],
        )

    # --- Command bar ---

    def _build_command_panel(self) -> Panel:
        storage_on = self._storage_state is not None
        s_label = "[S]断开存储" if storage_on else "[S]启用存储"
        s_style = f"bold {self._s['stat_bad']}" if storage_on else f"bold {self._s['stat_good']}"

        keys = Text()
        keys.append(f"  {s_label}", s_style)
        keys.append(f"  [M]模式", f"bold {self._s['accent']}")
        keys.append(f"  [W]写入", "bold #3498DB")
        keys.append(f"  [R]读取", "bold #3498DB")
        keys.append(f"  [I]状态", "bold #3498DB")
        keys.append(f"  [C]清除", "bold #3498DB")
        keys.append("  | ", "dim")
        keys.append(f"  [H]主题", "bold #F39C12")
        keys.append(f"  [P]RTT", "bold #F39C12")
        keys.append(f"  [T]吞吐", "bold #F39C12")
        keys.append(f"  [A]诊断", "bold #F39C12")
        keys.append("  | ", "dim")
        keys.append(f"  [Q]退出", f"bold {self._s['stat_bad']}")
        # Status message (expires after 5 seconds)
        msg = ""
        if self._status_msg and (monotonic() - self._status_time < 5.0):
            msg = self._status_msg
        t_line2 = Text()
        if msg:
            t_line2.append(f"  > {msg}", f"bold {self._s['stat_good']}")
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
        t.append(f"  最终虚拟容量:  {cap_str} {cap_unit}\n", self._s["stat_value"])
        t.append(f"  平均寻道时间:  {m.rtt_avg:.0f} ms\n", self._s["stat_value"])
        t.append(f"  总数据传输:    {dl_str} {dl_unit}\n", self._s["stat_value"])
        t.append(f"  丢包率:        {m.loss_rate * 100:.1f}%\n", self._s["stat_value"])
        t.append(f"\n  {select_exit_quote()}\n", "dim italic")
        return Panel(t, border_style=self._s["panel_border"])

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
    def _format_rate(bytes_per_sec: float) -> str:
        """Format bytes/sec into a human-readable rate string."""
        if bytes_per_sec <= 0:
            return "0 B/s"
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        idx = 0
        v = float(bytes_per_sec)
        while v >= 1024 and idx < len(units) - 1:
            v /= 1024
            idx += 1
        return f"{v:.0f} {units[idx]}"

    @staticmethod
    def _rtt_color(rtt: float) -> str:
        if rtt <= 0:
            return "dim"
        if rtt < 50:
            return "bold #2ECC71"
        if rtt < 200:
            return "bold white"
        if rtt < 500:
            return "bold #F39C12"
        return "bold #E74C3C"
