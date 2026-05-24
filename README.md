# LagDrive

> 网络延迟就是你的硬盘容量。

一个基于 **BDP（带宽时延乘积）** 原理的 Python CLI 工具——将网络延迟量化为虚拟存储空间，然后**真的在里面存数据**。

```
Capacity(bytes) = Bandwidth(bps) × RTT(s) / 8
```

![LagDrive](https://img.shields.io/badge/LagDrive-v1.1-blue) ![Python](https://img.shields.io/badge/Python-3.10+-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

## 它在干什么

简单说：你的网越卡，这块虚拟硬盘越大。而且你可以**真的往里面写数据**。

数据通过 Echo Relay 中继服务器在网络中循环传输——它一直"飘"在网线上。BDP 决定了能同时飘多少数据，也就是你的"存储容量"。断网？数据消失。这不是 bug，这是 feature。

- RTT 100ms + 带宽 50Mbps → 容量 **610 KB**
- RTT 500ms + 带宽 100Mbps → 容量 **5.96 MB**
- RTT 200ms + 带宽 1Gbps → 容量 **23.8 MB**

## 安装

```bash
git clone <repo-url>
cd LagDrive
pip install -e .
```

依赖：`rich>=13.0`、`psutil>=5.9`

## 使用

### 1. 启动 Echo Relay 服务器

存储功能需要一个运行中的 Relay。先启动它：

```bash
lagdrive --relay
lagdrive --relay --relay-port 9527          # 指定端口
lagdrive --relay --relay-host 0.0.0.0       # 监听所有接口
```

### 2. 写入 / 读取数据

```bash
# 写入数据
lagdrive --store "Hello, network storage!"

# 读回数据
lagdrive --read 0 23

# 查看存储状态
lagdrive --storage-info
```

### 3. 全屏仪表盘 + 存储

```bash
lagdrive --storage                          # 启用存储的仪表盘
lagdrive --storage -t 8.8.8.8              # 指定探测目标
```

仪表盘会显示存储状态面板和簇阵列中存储了数据的格子 `[S]`。

### 4. 探测模式（无需 Relay）

```bash
lagdrive                                    # 默认仪表盘（无存储）
lagdrive --probe-rtt                        # 单次 RTT 探测
lagdrive --probe-all                        # 完整诊断
lagdrive --bdp 200 100                      # BDP 换算器
lagdrive --snapshot                         # JSON 轮询模式
```

### Python API

```python
from lagdrive.api import LagDriveAPI

# ── 一次性探测 ──
rtt = LagDriveAPI.probe_rtt("1.1.1.1")
bdp = LagDriveAPI.compute_bdp(200, 100)
print(bdp["capacity_human"])  # "2.38 MB"

# ── 持续监控 ──
api = LagDriveAPI(target="1.1.1.1")
api.start()
snap = api.snapshot()
api.stop()

# ── 网络存储 ──
api = LagDriveAPI(storage_enabled=True, relay_host="127.0.0.1", relay_port=9527)
api.start()
api.write(b"Hello!")                   # 数据注入网络
data = api.read(0, 6)                  # 读回 b"Hello!"
info = api.storage_info()              # 存储状态
api.stop()
```

## 架构

```
lagdrive/
├── __init__.py      # CLI 入口
├── __main__.py      # python -m lagdrive
├── api.py           # LagDriveAPI — 编程接口
├── models.py        # 数据模型 (CellState, GridCell, NetworkMetrics, StorageBlock)
├── monitor.py       # TCP 探测引擎 (asyncio + ThreadPoolExecutor)
├── relay.py         # Echo Relay 服务器 + 线协议
├── storage.py       # RingBuffer + StorageClient
├── dashboard.py     # DiskGenius 风格 Rich 终端界面
└── quotes.py        # 讽刺语录系统 (42 条)
```

### 存储架构

```
客户端                                 Echo Relay
┌─────────────┐                       ┌──────────────┐
│ StorageClient│── WRITE frame ──────>│              │
│  ┌─────────┐ │<── ECHO frame ──────│  原样回传     │
│  │RingBuffer│ │                    │              │
│  └─────────┘ │                       └──────────────┘
│  Monitor     │  ← RTT/Throughput/BDP 更新 TTL 和容量
└─────────────┘
```

**线协议**：7 字节头 (`magic='LD'`, `type`, `length`) + body (`block_id + offset + data`)

**RingBuffer**：受 BDP 容量约束的环形缓冲区。块大小 64KB，最大 1024 块。TTL = `max(RTT×2×1.5, 0.5s)`，上限 30 秒。超时未确认的块被清零——这就是数据"消失"的瞬间。

### 簇阵列

- **`[S]`** 绿色 — 数据存储在网络传输中（Stored）
- **`[·]`** 蓝色 — 数据正在流动（Active）
- **`[ ]`** 灰色 — 未使用容量（Free）
- **`[!]`** 红色 — TCP 重传 / 延迟尖峰（Error）

### 讽刺语录

| 条件 | 示例 |
|------|------|
| RTT > 800ms | 检测到校园网巅峰性能，恭喜你获得了一块 10MB 的超大硬盘！ |
| RTT < 50ms | 警告：网速过快导致硬盘严重缩水，建议开启迅雷下载以维持容量。 |
| 丢包 > 5% | 检测到磁道物理损坏，正在请求 TCP 重传以修复坏道。 |
| 写入数据 | 数据已发射到网络平流层。请祈祷 Echo 雷达正常工作。 |
| 数据丢失 | 数据在传输中蒸发了。这不是 bug，这是量子存储。 |

## 测试

```bash
python test_api.py              # 全部测试（含网络探测）
python test_api.py --quick      # 跳过网络测试
python test_api.py --network    # 含吞吐量测试
```

测试覆盖：模块导入、Models 单元测试、语录路由、BDP 计算、Grid 状态机、API Snapshot、Dashboard 渲染、Monitor 生命周期、线协议、RingBuffer、Echo Relay、StorageClient 集成。

## Roadmap

- [x] **Phase 1 — Echo Relay 存储**：数据真的在网络中循环传输，BDP 就是真实容量
- [ ] **Phase 2 — RAID 0 (Striping) 模式**：同时向多个 Relay 发包，带宽叠加
- [ ] **Phase 3 — FUSE 挂载**：让你真的能在 L: 盘里放一个 txt（然后在断网的一瞬间眼睁睁看着它消失）

## License

MIT
