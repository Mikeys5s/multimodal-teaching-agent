"""答疑检索的**术语归一化** —— 修「中文提问查英文材料」的 0% 命中。

## 问题（2026-09-23 实测）

三份材料原文是**英文**（Ch03/05/06 原版），而 `search_kps` 是**词面匹配**
（中文 2-gram + 英文词重叠）。**纯中文 query 与英文文档没有任何交集**：

```
纯中文      命中 0 / 6      ← 「校验和是怎么算的？」→ 被误判为「材料里没有」
纯英文      命中 6 / 6
中文+英文    命中 6 / 6
```

**⚠️ 而"学生用中文提问"是默认行为** ⇒ **A3-1「检索命中率 ≥ 85%」按纯中文口径是 0%。**

## 怎么做

**在 `search_kps` 里，检索之前把 query 归一化**：
把 query 里出现的中文术语**追加**对应的英文原词 —— **不是替换**。

**为什么是追加而不是替换**：
- 替换会丢掉中文信息（有些术语的中文本身就出现在 `summary` 里）
- 追加让**中英两条通道都能命中**，而 `score_text` 本来就是取两者较高者

## 为什么不翻译全文

**没必要，也不该**：
1. 只需要覆盖**材料里出现过的术语** —— 而那是有限的
2. 术语是**事实映射**（"子网掩码" ↔ `subnet mask`），不是翻译
3. 翻译全文会引入幻觉风险（**而"幻觉率 0"是红线**）

## 维护方式

`TERMS` 是手写的，**但每一条都能在材料里找到出处**。
新增术语时：先确认它在材料里出现过，再配上英文原文的说法（**不是字典译法**）。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 术语表：中文说法 → 材料里的英文原词
#
# ⚠️ 英文一侧用**材料里的写法**（如 `three-way handshake` 不是 `3-way handshake`），
#    因为检索是词面匹配 —— **写法不一致就等于没配**。
#
# 分组注释只是为了可读，检索时一视同仁。
# ---------------------------------------------------------------------------

TERMS: dict[str, str] = {
    # ── Ch05 · 端到端协议（TCP / UDP）────────────────────────────────
    "三次握手": "three-way handshake",
    "三次握手协议": "three-way handshake",
    "握手": "handshake",
    "建立连接": "connection establishment",
    "连接建立": "connection establishment",
    "断开连接": "connection termination",
    "终止连接": "connection termination",
    "可靠字节流": "reliable byte stream",
    "字节流": "byte stream",
    "滑动窗口": "sliding window",
    "窗口": "window",
    "流量控制": "flow control",
    "流控": "flow control",
    "拥塞控制": "congestion control",
    "拥塞窗口": "congestion window",
    "通告窗口": "advertised window",
    "通告窗口大小": "advertised window",
    "确认号": "acknowledgement",
    "确认": "acknowledgement",
    "序号": "sequence number",
    "超时": "timeout",
    "超时重传": "adaptive retransmission",
    "自适应重传": "adaptive retransmission",
    "往返时间": "round-trip",
    "往返时延": "round-trip",
    "报文段": "segment",
    "段格式": "segment format",
    "复用": "demultiplexor",
    "解复用": "demultiplexor",
    "多路复用": "demultiplexor",
    "傻窗口综合症": "silly window",
    "糊涂窗口综合症": "silly window",
    "多路径": "multipath",
    "多路径 TCP": "multipath tcp",

    # ── Ch06 · 拥塞控制 ───────────────────────────────────────────────
    "慢启动": "slow start",
    "加性增乘性减": "additive increase",
    "加性增加乘性减少": "additive increase",
    "乘性减": "multiplicative decrease",
    "加性增": "additive increase",
    "拥塞避免": "congestion avoidance",
    "队列": "queuing",
    "排队": "queuing",
    "排队规则": "queuing disciplines",
    "资源分配": "resource allocation",
    "公平排队": "fair queuing",
    "主动队列管理": "active queue management",
    "随机早期检测": "random early detection",
    "往返延迟": "round-trip",

    # ── Ch03 · 网络互联（IP / 路由）──────────────────────────────────
    "子网": "subnet",
    "子网划分": "subnetting",
    "子网掩码": "subnet mask",
    "掩码": "subnet mask",
    "网络号": "network number",
    "网络地址": "network number",
    "转发": "forwarding",
    "转发表": "forwarding table",
    "路由表": "forwarding table",
    "数据报": "datagram",
    "数据包": "datagram",
    "分组": "packet",
    "分片": "fragmentation",
    "重组": "reassembly",
    "IP 数据报": "ip datagram",
    "校验和": "checksum",
    "首部": "header",
    "生存时间": "ttl",
    "跳数": "hop count",
    "地址解析": "arp",
    "地址解析协议": "arp",
    "动态主机配置": "dhcp",
    "动态主机配置协议": "dhcp",
    "差错报告": "icmp",
    "差错报告协议": "icmp",
    "网际控制报文协议": "icmp",

    # ── Ch03 · 路由协议 ──────────────────────────────────────────────
    "距离向量": "distance-vector",
    "距离矢量": "distance-vector",
    "链路状态": "link-state",
    "链路状态路由": "link-state routing",
    "路由": "routing",
    "路由协议": "routing protocol",
    "路由算法": "routing",
    "最短路": "lowest-cost path",
    "最小开销路径": "lowest-cost path",
    "自治系统": "autonomous system",
    "域内路由": "intradomain",
    "域间路由": "interdomain",
    "链路状态分组": "link-state packet",
    "链路状态报文": "link-state packet",
    "泛洪": "flooding",
    "源路由": "source route",
    "虚拟专网": "vpn",
    "虚拟专用网": "vpn",
    "隧道": "tunnel",
    "封装": "encapsulation",
    "网络地址转换": "nat",
    "地址转换": "nat",

    # ── 通用 ─────────────────────────────────────────────────────────
    "吞吐量": "throughput",
    "带宽": "bandwidth",
    "时延": "delay",
    "延迟": "delay",
    "丢包": "loss",
    "重传": "retransmission",
    "以太网": "ethernet",
    "地址": "address",
    "协议": "protocol",
}

# 检索时最多追加这么多英文词 —— **太多会把无关文档也拉进来**
MAX_APPENDED = 6


def normalize_query(query: str) -> str:
    """把 query 里出现的中文术语**追加**对应英文原词（**不替换**）。

    >>> normalize_query("校验和是怎么算的？")
    '校验和是怎么算的？ checksum'
    >>> normalize_query("HELLO")
    'HELLO'

    **为什么追加而不是替换**：替换会丢掉中文一侧的信息；
    而 `score_text` 对两个通道取**较高者**，所以追加只会让命中变多、不会变少。

    ## ⚠️ 必须去重（2026-09-23 实测踩到）

    多个中文术语会映射到**同一个英文**：

    ```
    「子网掩码是怎么用的？」  ← 同时命中「子网」「子网掩码」「掩码」
    → 旧输出：... subnet subnet mask subnet mask     ← 重复追加
    → 修复后：... subnet subnet mask                 ← 用 dict 保序去重
    ```

    **重复追加不会让分数变高**（`score_text` 用的是**集合交集**，
    重复词在 set 里只算一次）—— 但它会让 query 变长、白占 `MAX_APPENDED` 名额，
    **把真正需要的术语挤掉**。所以按**首次出现顺序**去重。
    """
    if not query:
        return query

    low = query.lower()
    # dict 保序：既去重，又保持「术语表里的先后顺序」
    added: dict[str, None] = {}
    for zh, en in TERMS.items():
        if zh in query and en.lower() not in low:
            added[en] = None            # 同一英文只留一次
            if len(added) >= MAX_APPENDED:
                break

    if not added:
        return query
    return f"{query} {' '.join(added)}"


def explain(query: str) -> list[tuple[str, str]]:
    """返回这次命中了哪些术语映射（**用于排查与举证**）。"""
    return [(zh, en) for zh, en in TERMS.items() if zh in (query or "")]
