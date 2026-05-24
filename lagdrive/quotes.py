"""Sarcastic quote system — because your network deserves verbal abuse."""

import random

# Category: RTT spikes (> 800ms)
RTT_APOCALYPSE: list[str] = [
    "检测到校园网巅峰性能，恭喜你获得了一块 10MB 的超大硬盘！",
    "延迟破千！你的网线正在用 Morse 码传数据。",
    "寻道时间超过了硬盘的自尊心。建议重启人生。",
    "这延迟够你泡杯茶、洗个澡、再写封遗书了。",
    "检测到光速在你家网线中降到了步行速度。",
    "RTT 超过 1 秒——你确定用的不是信鸽？",
    "恭喜！你的延迟已经超过了火星到地球的通信时延。",
]

# Category: Excellent network (< 50ms)
RTT_FAST: list[str] = [
    "警告：网速过快导致硬盘严重缩水，建议开启迅雷下载以维持容量。",
    "延迟太低了，你的虚拟硬盘正在坍缩成一个点。",
    "网络太快，硬盘容量已不足一张软盘。这是胜利还是悲哀？",
    "检测到正常网络连接——LagDrive 正在考虑转行。",
    "延迟低于 50ms？这不是校园网，你在用什么黑科技？",
]

# Category: Packet loss (> 5%)
PACKET_LOSS: list[str] = [
    "检测到磁道物理损坏，正在请求 TCP 重传以修复坏道。",
    "你的数据包正在进行一场说走就走的旅行，有些再也没回来。",
    "丢包率爆表！你的网线正在举行数据葬礼。",
    "多个扇区报错——建议对网线进行物理超度。",
    "TCP 忙着重传，ICMP 在旁边看热闹。",
    "数据包正在表演魔术：从你的网卡消失，在 /dev/null 中出现。",
]

# Category: Traffic milestone (> 1GB)
TRAFFIC_HIGH: list[str] = [
    "这块硬盘已经烧掉了你一顿外卖的流量钱。",
    "流量破 GB！你的运营商正在给你写感谢信。",
    "已消耗的流量足以下载一部 480p 的电影。画面质量约等于马赛克。",
    "流量计费用户的噩梦，包月用户的无所谓。",
    "数据传输量已超过阿波罗 11 号登月时的全部通信量。你的成就：刷了个网页。",
]

# Category: Low throughput
THROUGHPUT_LOW: list[str] = [
    "读写速度感人，约等于用吸管喝奶昔。",
    "顺序读取速度：一只训练有素的信鸽也能更快。",
    "检测到你的带宽正在用「bit」而不是「Mbps」做单位。",
    "这个读写速度，机械硬盘看了都会笑出声。",
    "带宽不足以流畅加载纯文本网页。这是 1995 年吗？",
]

# Category: High throughput
THROUGHPUT_HIGH: list[str] = [
    "带宽充足但延迟爆炸——典型的水管够粗，但水在里面游泳。",
    "高带宽高延迟：一辆法拉利堵在了早高峰的立交桥上。",
    "读写速度起飞！可惜每飞一步都要停下来问路。",
]

# Category: Large capacity
CAPACITY_BIG: list[str] = [
    "虚拟容量已超过你第一台电脑的物理硬盘。讽刺吗？",
    "容量持续增长中！建议申请联合国世界遗产保护。",
    "这块硬盘的容量取决于你有多惨——越卡越大，公平公正。",
    "恭喜！你已拥有一块由纯粹痛苦凝聚而成的超大容量硬盘。",
]

# Category: Neutral / observation
NEUTRAL: list[str] = [
    "LagDrive: 把网络延迟变成存储焦虑的创新解决方案。",
    "正在持续监控中...你的网络一如既往地令人失望。",
    "技术声明：BDP 公式证明你的网费交了个寂寞。",
    "一切数据均为虚拟，但你的痛苦是真实的。",
    "每 2 秒探测一次，就像你的网络一样，定时抽风。",
]

# Category: Storage write
STORAGE_WRITE: list[str] = [
    "数据已发射到网络平流层。请祈祷 Echo 雷达正常工作。",
    "你的数据正在进行一场说走就走的旅行，目的地：未知。",
    "已将数据注入网线。当前正以光速的 0.1% 在路由器迷宫中流浪。",
]

# Category: Data loss / expiry
STORAGE_LOST: list[str] = [
    "数据在传输中蒸发了。这不是 bug，这是量子存储。",
    "你的数据已经完成了它的生命周期：出生、传输、消亡。",
    "检测到数据丢失。建议向你的路由器献花默哀。",
]

# Category: Storage confirmation
STORAGE_CONFIRMED: list[str] = [
    "数据往返成功！你的网线今天心情不错。",
    "Echo 确认收到。数据在传输中幸存——了不起的成就。",
    "数据完成了网络旅行并安全返回。这大概是它人生中最没意义的旅程。",
]


def select_quote(
    rtt_avg: float,
    loss_rate: float,
    total_downloaded: int,
    throughput_avg: float,
    capacity: float,
    storage_event: str | None = None,
) -> str:
    """Select a contextually appropriate sarcastic quote.

    Priority: storage events > loss > RTT extremes > traffic > throughput > capacity > neutral
    """
    # Storage events take top priority
    if storage_event == "write":
        return random.choice(STORAGE_WRITE)
    if storage_event == "lost":
        return random.choice(STORAGE_LOST)
    if storage_event == "confirmed":
        return random.choice(STORAGE_CONFIRMED)

    # Network down — all probes failed
    if rtt_avg <= 0 and loss_rate >= 0.99:
        return random.choice(PACKET_LOSS)

    # Terrible latency
    if rtt_avg > 800:
        return random.choice(RTT_APOCALYPSE)

    # Excellent latency (the "problem")
    if 0 < rtt_avg < 50:
        return random.choice(RTT_FAST)

    # Packet loss
    if loss_rate > 0.05:
        return random.choice(PACKET_LOSS)

    # Traffic milestone
    if total_downloaded > 1_000_000_000:
        return random.choice(TRAFFIC_HIGH)

    # Low throughput
    if 0 < throughput_avg < 1.0:
        return random.choice(THROUGHPUT_LOW)

    # High throughput with high latency
    if throughput_avg > 50 and rtt_avg > 200:
        return random.choice(THROUGHPUT_HIGH)

    # Large capacity
    if capacity > 5_000_000:
        return random.choice(CAPACITY_BIG)

    # 40% chance of neutral commentary
    if random.random() < 0.4:
        return random.choice(NEUTRAL)

    # Fallback — pick from any RTT-adjacent category
    if rtt_avg > 200:
        return random.choice(RTT_APOCALYPSE)
    return random.choice(NEUTRAL)
