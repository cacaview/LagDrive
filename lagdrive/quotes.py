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
    "你的数据包正在网线里度假，顺便环游了世界。",
    "检测到延迟高峰。你的数据可能正在某个路由器上排队买奶茶。",
    "网络延迟已经长到可以用来测量天文学距离了。",
    "这不是延迟，这是时间膨胀。爱因斯坦看了都沉默。",
    "你的 ping 值已经可以和树懒的反应速度一较高下了。",
    "数据包发出去了，回不回来全看缘分。",
]

# Category: Excellent network (< 50ms)
RTT_FAST: list[str] = [
    "警告：网速过快导致硬盘严重缩水，建议开启迅雷下载以维持容量。",
    "延迟太低了，你的虚拟硬盘正在坍缩成一个点。",
    "网络太快，硬盘容量已不足一张软盘。这是胜利还是悲哀？",
    "检测到正常网络连接——LagDrive 正在考虑转行。",
    "延迟低于 50ms？这不是校园网，你在用什么黑科技？",
    "你的网络太流畅了，LagDrive 感受到了生存危机。",
    "网速快到硬盘容量只剩下一个字节了。存什么都嫌多。",
    "高速网络检测完毕。LagDrive 建议你故意下载点什么来增加容量。",
]

# Category: Packet loss (> 5%)
PACKET_LOSS: list[str] = [
    "检测到磁道物理损坏，正在请求 TCP 重传以修复坏道。",
    "你的数据包正在进行一场说走就走的旅行，有些再也没回来。",
    "丢包率爆表！你的网线正在举行数据葬礼。",
    "多个扇区报错——建议对网线进行物理超度。",
    "TCP 忙着重传，ICMP 在旁边看热闹。",
    "数据包正在表演魔术：从你的网卡消失，在 /dev/null 中出现。",
    "丢包就像放屁——你知道它发生了，但你拦不住。",
    "你的网络可靠性堪比纸质雨伞。",
    "检测到丢包。你的数据正在 /dev/null 里开派对。",
    "数据包的存活率比彩票中奖率还低。",
]

# Category: Traffic milestone (> 1GB)
TRAFFIC_HIGH: list[str] = [
    "这块硬盘已经烧掉了你一顿外卖的流量钱。",
    "流量破 GB！你的运营商正在给你写感谢信。",
    "已消耗的流量足以下载一部 480p 的电影。画面质量约等于马赛克。",
    "流量计费用户的噩梦，包月用户的无所谓。",
    "数据传输量已超过阿波罗 11 号登月时的全部通信量。你的成就：刷了个网页。",
    "恭喜！你今天消耗的流量够发 100 万封电子邮件了。你却只存了个 Hello World。",
    "流量用量已经可以申请运营商 VIP 了。请hold住。",
    "你的数据传输量足以把整部《大英百科全书》在网线里来回寄 50 遍。",
]

# Category: Low throughput
THROUGHPUT_LOW: list[str] = [
    "读写速度感人，约等于用吸管喝奶昔。",
    "顺序读取速度：一只训练有素的信鸽也能更快。",
    "检测到你的带宽正在用「bit」而不是「Mbps」做单位。",
    "这个读写速度，机械硬盘看了都会笑出声。",
    "带宽不足以流畅加载纯文本网页。这是 1995 年吗？",
    "你的带宽窄到数据包需要排队单文件通过。",
    "吞吐量低到可以和蜗牛赛跑——蜗牛赢。",
    "读写速度堪比在石头上刻字。建议改用竹简。",
]

# Category: High throughput
THROUGHPUT_HIGH: list[str] = [
    "带宽充足但延迟爆炸——典型的水管够粗，但水在里面游泳。",
    "高带宽高延迟：一辆法拉利堵在了早高峰的立交桥上。",
    "读写速度起飞！可惜每飞一步都要停下来问路。",
    "带宽拉满，延迟拉胯。就像一辆没有方向盘的跑车。",
    "吞吐量很高，但数据包每到一个路由器都要停下来自拍。",
]

# Category: Large capacity
CAPACITY_BIG: list[str] = [
    "虚拟容量已超过你第一台电脑的物理硬盘。讽刺吗？",
    "容量持续增长中！建议申请联合国世界遗产保护。",
    "这块硬盘的容量取决于你有多惨——越卡越大，公平公正。",
    "恭喜！你已拥有一块由纯粹痛苦凝聚而成的超大容量硬盘。",
    "你的虚拟硬盘比你的人生规划还要大。",
    "容量大到可以装下你所有的遗憾了。",
    "建议把这块硬盘命名为「卡顿纪念碑」。",
]

# Category: Neutral / observation
NEUTRAL: list[str] = [
    "LagDrive: 把网络延迟变成存储焦虑的创新解决方案。",
    "正在持续监控中...你的网络一如既往地令人失望。",
    "技术声明：BDP 公式证明你的网费交了个寂寞。",
    "一切数据均为虚拟，但你的痛苦是真实的。",
    "每 2 秒探测一次，就像你的网络一样，定时抽风。",
    "LagDrive 提醒您：网速和心情成反比。",
    "温馨提示：你正在为一块看不见摸不着的硬盘工作。",
    "你的网络状态：薛定谔的连接——在你 ping 之前，它同时是通的和不通的。",
]

# Category: Storage write
STORAGE_WRITE: list[str] = [
    "数据已发射到网络平流层。请祈祷 Echo 雷达正常工作。",
    "你的数据正在进行一场说走就走的旅行，目的地：未知。",
    "已将数据注入网线。当前正以光速的 0.1% 在路由器迷宫中流浪。",
    "数据已送出。它现在属于互联网了。",
    "写入成功。数据正在以光速的零头穿越你的网络基础设施。",
    "数据发射完毕。目前状态：薛定谔的存储。",
]

# Category: Data loss / expiry
STORAGE_LOST: list[str] = [
    "数据在传输中蒸发了。这不是 bug，这是量子存储。",
    "你的数据已经完成了它的生命周期：出生、传输、消亡。",
    "检测到数据丢失。建议向你的路由器献花默哀。",
    "数据走了，但它的精神永存。安息吧，小字节们。",
    "存储过期。数据已化作网线中的噪声，回归自然。",
    "数据消失。就像你的耐心一样——来得快，去得更快。",
]

# Category: Storage confirmation
STORAGE_CONFIRMED: list[str] = [
    "数据往返成功！你的网线今天心情不错。",
    "Echo 确认收到。数据在传输中幸存——了不起的成就。",
    "数据完成了网络旅行并安全返回。这大概是它人生中最没意义的旅程。",
    "数据活着回来了！建议给它颁一个穿越网络的勇气勋章。",
    "存储确认。数据在网线里走了一圈，毫发无损。今天是个好日子。",
    "数据安然无恙。看来你的路由器今天没有搞破坏。",
]

# Category: Exit messages
EXIT_QUOTES: list[str] = [
    "所有数据已清空。就像你的带宽一样——从未真正存在过。",
    "会话结束。你的数据回到了它来的地方——虚无。",
    "LagDrive 已退出。网络延迟还在，但快乐没了。",
    "虚拟硬盘已卸载。你的网线终于可以休息了。",
    "再见！下次卡顿的时候记得想起我们。",
    "LagDrive 关闭。你的路由器终于可以松一口气了。",
    "存储已释放。数据化作比特流，消散在网络的深渊中。",
    "退出完成。感谢你用卡顿换来了这一段荒唐的存储体验。",
    "会话结束。那些数据就像你的青春——一去不复返。",
    "再见！愿你的延迟永远够大，容量永远够用。",
    "LagDrive 说拜拜。记住：真正的硬盘从来不会消失。但这个会。",
    "关闭。你的网线现在空空如也，就像刚格式化的硬盘。",
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


def select_exit_quote() -> str:
    """Select a random exit farewell quote."""
    return random.choice(EXIT_QUOTES)
