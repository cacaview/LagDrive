# LagDrive

> 网络延迟就是你的硬盘容量。

一个基于 **BDP（带宽时延乘积）** 原理的 Python CLI 工具——将网络延迟量化为虚拟存储空间，然后**真的在里面存数据**。

```
Capacity(bytes) = Bandwidth(bps) × RTT(s) / 8
```

![LagDrive](https://img.shields.io/badge/LagDrive-v1.2-blue) ![Python](https://img.shields.io/badge/Python-3.10+-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

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

依赖：`rich>=13.0`

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

### 3.1 RAID 多副本存储模式

LagDrive 支持 RAID 0/1/5/10 多 Relay 存储模式，数据同时在多条网络管道中传输：

```bash
# 启动多个 Echo Relay（需多个终端或不同端口）
lagdrive --relay --relay-port 9527
lagdrive --relay --relay-port 9528

# RAID 0 — 条带化：数据分散到多个 Relay，带宽叠加，无冗余
lagdrive --raid-mode raid0 --relays 127.0.0.1:9527 127.0.0.1:9528 --store "hello RAID0"

# RAID 1 — 镜像：每个块复制到所有 Relay，冗余完整
lagdrive --raid-mode raid1 --relays 127.0.0.1:9527 127.0.0.1:9528 --store "hello RAID1"

# RAID 5 — 条带 + 分布式校验（需 ≥ 3 Relay，可容忍 1 个故障）
lagdrive --raid-mode raid5 --relays 127.0.0.1:9527 127.0.0.1:9528 127.0.0.1:9529 --store "hello RAID5"

# RAID 10 — 镜像 + 条带（需 ≥ 4 Relay，且为偶数个）
lagdrive --raid-mode raid10 --relays 127.0.0.1:9527 127.0.0.1:9528 127.0.0.1:9529 127.0.0.1:9530 --store "hello RAID10"

# 读取数据（RAID 模式下读回的是原始数据，校验块自动排除）
lagdrive --raid-mode raid0 --relays 127.0.0.1:9527 127.0.0.1:9528 --read 0 10

# RAID 模式仪表盘
lagdrive --raid-mode raid0 --relays 127.0.0.1:9527 127.0.0.1:9528 --storage
```

| RAID 模式 | 最少 Relay | 冗余 | 容量倍数 | 特点 |
|-----------|-----------|------|---------|------|
| RAID 0 | 2 | 无 | ×N | 带宽叠加，一个挂全挂 |
| RAID 1 | 2 | N 份 | ×1 | 完整冗余，带宽不增 |
| RAID 5 | 3 | 1 份校验 | ×(N-1) | 可容忍 1 个 Relay 故障，自动 XOR 重建，Per-Relay RTT 独立测量 |
| RAID 10 | 4 (偶数) | 镜像对 | ×(N/2) | 又快又安全 |

RAID 5 故障检测：每个 tick 轮询各 Relay 的连接状态，故障 Relay 被跳过，降级模式下自动触发 XOR 重建读取。仪表盘显示每个 Relay 的地址、存活状态和独立 RTT。按 `M` 可在运行时切换 RAID 模式。

### 4. 探测模式（无需 Relay）

```bash
lagdrive                                    # 默认仪表盘（无存储）
lagdrive --probe-rtt                        # 单次 RTT 探测
lagdrive --probe-throughput                 # 单次吞吐量测试
lagdrive --probe-all                        # 完整诊断
lagdrive --bdp 200 100                      # BDP 换算器
lagdrive --snapshot                         # JSON 轮询模式
```

### 5. 交互式仪表盘快捷键

全屏仪表盘模式下，底部命令栏支持以下快捷键：

| 按键 | 功能 | 说明 |
|------|------|------|
| `S` | 启用/断开存储 | 连接或断开 Echo Relay |
| `M` | 切换 RAID 模式 | 交互式选择 RAID 级别和 Relay 地址 |
| `W` | 写入数据 | 输入文本，注入网络存储 |
| `R` | 读取数据 | 按 offset/length 读回数据 |
| `I` | 存储状态 | 在命令栏显示当前存储信息 |
| `C` | 清除存储 | 清空所有网络中的数据块 |
| `P` | RTT 探测 | 单次 TCP RTT 测量 |
| `T` | 吞吐量测试 | 单次带宽测量 |
| `A` | 完整诊断 | RTT + 吞吐量 + BDP |
| `B` | BDP 计算器 | 输入 RTT 和带宽换算容量 |
| `Q` | 退出 | 关闭仪表盘 |

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

# ── RAID 多副本存储 ──
api = LagDriveAPI(target="1.1.1.1")
api.enable_raid_storage(
    relays=[("127.0.0.1", 9527), ("127.0.0.1", 9528)],
    mode="raid0",  # "raid0", "raid1", "raid5", "raid10"
)
api.start()
api.write(b"Hello RAID!")              # 数据条带化分发
info = api.storage_info()              # 包含 raid_mode 和 relay_count
api.stop()
```

## 架构

```
lagdrive/
├── __init__.py      # CLI 入口
├── __main__.py      # python -m lagdrive
├── api.py           # LagDriveAPI — 编程接口
├── models.py        # 数据模型 (CellState, GridCell, NetworkMetrics, StorageBlock, RAIDMode)
├── monitor.py       # TCP 探测引擎 (asyncio + ThreadPoolExecutor)
├── relay.py         # Echo Relay 服务器 + 线协议
├── storage.py       # RingBuffer + StorageClient
├── raid.py          # RAIDStorageClient — RAID 0/1/5/10 多副本存储
├── dashboard.py     # DiskGenius 风格 Rich 终端界面
└── quotes.py        # 讽刺语录系统 (90+ 条，含 RAID 语录)
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

共 124 条，覆盖 14 个场景：

| 条件 | 示例 |
|------|------|
| RTT > 800ms | 这不是延迟，这是时间膨胀。爱因斯坦看了都沉默。 |
| RTT < 50ms | 网速快到硬盘容量只剩下一个字节了。存什么都嫌多。 |
| 丢包 > 5% | 丢包就像放屁——你知道它发生了，但你拦不住。 |
| 写入数据 | 数据已送出。它现在属于互联网了。 |
| 数据过期 | 存储过期。数据已化作网线中的噪声，回归自然。 |
| 数据确认 | 数据安然无恙。看来你的路由器今天没有搞破坏。 |
| RAID 降级 | 一个 Relay 挂了。XOR 校验顶一阵。数学是最好的冗余。 |
| RAID 恢复 | 所有 Relay 恢复在线。系统从降级模式中醒来。硬盘从不睡觉。 |
| 退出 | 你的网线现在空空如也，就像刚格式化的硬盘。 |
| 操作提示 | 40% 概率附带嘲讽后缀，如 "写入成功。一切正常。暂时。" |

## 测试

```bash
python test_api.py              # 全部测试（含网络探测）
python test_api.py --quick      # 跳过网络测试
python test_api.py --network    # 含吞吐量测试
```

测试覆盖：模块导入、Models 单元测试、语录路由、BDP 计算、Grid 状态机、API Snapshot、Dashboard 渲染、Monitor 生命周期、线协议、RingBuffer、Echo Relay、StorageClient 集成。

## Roadmap

- [x] **Phase 1 — Echo Relay 存储**：数据真的在网络中循环传输，BDP 就是真实容量
- [x] **Phase 2 — RAID 多副本存储**：同时向多个 Relay 发包，支持 RAID 0（条带）、RAID 1（镜像）、RAID 5（校验 + 故障检测 + XOR 在线重建 + Per-Relay RTT）、RAID 10（镜像条带）
- [ ] **Phase 3 — FUSE 挂载**：让你真的能在 L: 盘里放一个 txt（然后在断网的一瞬间眼睁睁看着它消失）

## License

MIT
