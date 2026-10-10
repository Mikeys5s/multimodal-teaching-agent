# -*- coding: utf-8 -*-
"""
会话导出结果的独立校验。

刻意不走 export-conversation.py 的解析路径：这里直接在字节层面数
`"type":"xxx"` 的出现次数，用不同的观测手段对账，避免"自己验证自己"。

用法:
    python scripts/verify-conversation-export.py "<源.jsonl>" "<导出目录>"
"""
import io
import os
import json
import sys

OK, FAIL = '✅', '❌'
fails = []


def check(name, got, want, note=''):
    ok = (got == want)
    print('  %s %-42s 实际 %s / 期望 %s %s' % (OK if ok else FAIL, name, got, want, note))
    if not ok:
        fails.append(name)
    return ok


def check_tail(name, got, want, tol=50, note=''):
    """**尾部计数**的宽松判据 —— 允许 `got` 比 `want` **少一点**（活跃会话的正常现象）。

    ## 为什么要这个（2026-10-11）

    导出的会话**可能正在写入**（当前会话本身就在往里写）。
    脚本的设计是「**最后一行不完整时跳过，不报错**」——
    于是**末尾几个事件**不会进导出 ⇒ 计数**必然少几条**。

    **实测**：241/242 · 2080/2087 · 4922/4933 —— **差值全在文件末尾**。

    ## 为什么不用"全局容忍"

    **只有"会被活跃写入影响"的项才该宽松**（各类事件计数）。
    `轮次数` / `日期章节数` / `分册文件数` 这些是**结构性的**，
    **少一个就是真错**，必须精确相等。

    ## 判据

    `got <= want` 且 `want - got <= tol` ⇒ 通过。
    **`got > want` 一定判失败**（导出比源多 = 解析器把同一事件算了两次）。
    """
    ok = (got <= want) and (want - got <= tol)
    tail = f'（少 {want - got} 条 —— 活跃会话的尾部）' if got < want else ''
    print('  %s %-42s 实际 %s / 期望 %s %s%s'
          % (OK if ok else FAIL, name, got, want, note, tail))
    if not ok:
        fails.append(name)
    return ok


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, outdir = sys.argv[1], sys.argv[2]

    print('源文件：%s' % src)
    raw = open(src, 'rb').read()
    print('  大小 %.1f MB' % (len(raw) / 1024 / 1024))

    # ---- 1) 源文件计数 ----
    # 两种观测手段：
    #   (a) 字节级：快，但会把 function_call_result 里**回显的**同名字符串也算进来
    #       （实测 input_text 被多算 87 次，全部来自工具输出回显）
    #   (b) 解析级：按记录类型逐项数，作为对账的权威值
    print('\n[1] 源文件事件计数')
    b_in = raw.count(b'"type":"input_text"')
    b_call = raw.count(b'"type":"function_call"')
    b_call2 = raw.count(b'"type":"function_call_result"')
    b_out = raw.count(b'"type":"output_text"')
    b_think = raw.count(b'"type":"reasoning"')
    print('    (a) 字节级：input_text=%d  output_text=%d  function_call=%d  result=%d  reasoning=%d'
          % (b_in, b_out, b_call, b_call2, b_think))

    a_in = a_out = a_img = a_call = a_res = a_think = a_think_ne = 0
    bad = 0
    with io.open(src, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                bad += 1
                continue
            t = o.get('type')
            if t == 'message':
                for it in (o.get('content') or []):
                    if not isinstance(it, dict):
                        continue
                    k = it.get('type')
                    if k == 'input_text':
                        a_in += 1
                    elif k == 'output_text':
                        a_out += 1
                    elif k == 'image_blob_ref':
                        a_img += 1
            elif t == 'function_call':
                a_call += 1
            elif t == 'function_call_result':
                a_res += 1
            elif t == 'reasoning':
                a_think += 1
                rc = o.get('rawContent')
                if isinstance(rc, list):
                    txt = ''.join((x.get('text') or '') if isinstance(x, dict) else str(x) for x in rc)
                elif isinstance(rc, str):
                    txt = rc
                else:
                    txt = ''
                if txt.strip():
                    a_think_ne += 1
    print('    (b) 解析级：input_text=%d  output_text=%d  image=%d  function_call=%d  result=%d  reasoning=%d（其中非空 %d）'
          % (a_in, a_out, a_img, a_call, a_res, a_think, a_think_ne))
    print('    差异说明：字节级 input_text 多出的 %d 次来自 function_call_result 内回显；'
          % (b_in - a_in))
    print('              空 rawContent 的 reasoning 记录 %d 条（不入档，已在 stats 登记）' % (a_think - a_think_ne))
    check('源文件无损坏行', bad, 0)

    stats = json.load(io.open(os.path.join(outdir, 'raw', 'stats.json'), encoding='utf-8'))

    print('\n[2] 导出统计 vs 源文件')
    # ⚠️ 这几项**会被"活跃会话的尾部"影响**（脚本会跳过不完整的最后一行）
    #    ⇒ 用 `check_tail`（允许少几条、绝不允许多）
    check_tail('助手回复段数', stats['assistant_messages'], a_out)
    check_tail('用户提问条数', stats['user_messages'], a_in)
    check_tail('工具调用次数', stats['tool_calls'], a_call)
    check_tail('工具返回条数', stats['tool_results'], a_res)

    # ---- 3) raw jsonl 自洽 ----
    print('\n[3] raw/conversation.jsonl 自洽')
    rp = os.path.join(outdir, 'raw', 'conversation.jsonl')
    nlines = 0
    kinds = {}
    with io.open(rp, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            nlines += 1
            o = json.loads(ln)
            kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
    print('    行数 %d，分布 %s' % (nlines, kinds))
    # ⚠️ 这一项是**各分量期望值之和** —— 每个分量都可能少几条（活跃会话尾部），
    #    **误差会累加** ⇒ 公差要按**分量个数**放大（6 类 × 50 = 300）。
    check_tail('jsonl 行数 = 各类型事件数之和', nlines,
               a_in + a_out + a_img + a_call + a_res + a_think_ne, tol=300)
    check_tail('jsonl 中 reasoning 条数', kinds.get('think', 0), a_think_ne)
    check_tail('jsonl 中 tool 条数', kinds.get('tool', 0), a_call)
    check_tail('jsonl 中 result 条数', kinds.get('result', 0), a_res)
    check_tail('jsonl 中 user 条数', kinds.get('user', 0), a_in)
    check_tail('jsonl 中 asst 条数', kinds.get('asst', 0), a_out)
    check('stats 登记的空思考数', stats['reasoning']['empty_skipped'], a_think - a_think_ne)
    check('jsonl 中 img 条数', kinds.get('img', 0), a_img)

    # ---- 4) 主文档可读性与完整性 ----
    print('\n[4] 主文档检查')
    md = io.open(os.path.join(outdir, '会话记录-完整版.md'), encoding='utf-8').read()
    check_tail('用户块数', md.count('**👤 用户**'), a_in)
    check('助手块数 ≤ 用户块数', md.count('**🤖 助手**') <= a_in + 1, True,
          '（一轮可能没有可见助手输出）')
    # ⚠️ **注入块残留：用「导出脚本自己记的数」判，不用文本特征**（2026-10-11 定）
    #
    # 走过两条弯路：
    #   ① `md.count('system-reminder')` ⇒ **对话正文会引用这个词**（我们真的讨论过它）
    #   ② 加严到 `data-role="user-context"` / `<user_info>` ⇒ **还是假阳性** ——
    #      **因为我在正文里举例写过这段**（10/7 那次分析里就原样写了）。
    #   ⇒ **根本原因：导出后就是纯文本，"真注入块"和"我们引用它"在字节上不可区分。**
    #
    # ✅ **正解**：**导出脚本自己知道它剥了多少** —— `raw/stats.json` 里有
    #    · `system_injections_stripped`（实际剥掉的块数）
    #    · `leftover_injection_tags`（剥离后残留的标签数）
    #    **校验器只该验后者为 0**，并把前者**记下来供对账**。
    #    **⇒ 判据要锚在"知道原因的那一层"，不要在下游猜。**
    check('注入块残留标签（脚本自记）', stats.get('leftover_injection_tags', -1), 0)
    print('  ·  %-42s 实际 %s 个（已剥离，供对账）'
          % ('注入块剥离数（脚本自记）', stats.get('system_injections_stripped', '?')))
    check('user_query 标签残留', md.count('<user_query>'), 0)
    check('轮次标题数', md.count('\n## 轮次 '), stats['turns'])
    check('日期章节数', md.count('\n# 2026-'), len(stats['by_date']))
    check('无流式占位碎片 OK.', md.count('\nOK.\n'), 0)
    check('无流式占位碎片 Let me go.', md.count('Let me go.'), 0)

    # 工具调用总数（展开 ×N 后）应与来源一致
    import re
    tot = 0
    for m in re.finditer(r'^- ⚙️ \*\*([A-Za-z_]+)\*\*(.*)$', md, re.M):
        tail = m.group(2)
        mm = re.search(r'（×(\d+)）\s*$', tail)
        tot += int(mm.group(1)) if mm else 1
    check_tail('工具调用行展开合计', tot, a_call)

    # ---- 5) 按天分册 ----
    print('\n[5] 按天分册')
    files = sorted(x for x in os.listdir(os.path.join(outdir, 'by-date')) if x.endswith('.md'))
    check('分册文件数', len(files), len(stats['by_date']))
    tot_turns = 0
    for x in files:
        t = io.open(os.path.join(outdir, 'by-date', x), encoding='utf-8').read()
        tot_turns += t.count('\n## 轮次 ')
        check('  %s 轮次数' % x, t.count('\n## 轮次 '), stats['by_date'][x[:-3]]['turns'])
    check('分册轮次合计 = 总轮次', tot_turns, stats['turns'])

    # ---- 6) HTML ----
    print('\n[6] HTML 浏览版')
    html = io.open(os.path.join(outdir, 'index.html'), encoding='utf-8').read()
    # ⚠️ 同上：**用脚本自记的数**，不用文本特征（HTML 里更容易被"我们引用它时的举例"命中）。
    print('  ·  %-42s 实际 %s 次（含对话正文里的引用与举例，非残留）'
          % ('（参考）HTML 里 system-reminder 字样', html.count('system-reminder')))
    check('HTML 章节数 ≤ 轮次数', html.count('<section id="turn-') <= stats['turns'], True)
    check('HTML 用户块数 = 主文档用户块数',
          html.count('<div class="who">👤 用户'), md.count('**👤 用户**'))

    print('\n' + '=' * 62)
    if fails:
        print('%s 校验未通过 %d 项：%s' % (FAIL, len(fails), ', '.join(fails)))
        return 1
    print('%s 全部校验通过' % OK)
    return 0


if __name__ == '__main__':
    sys.exit(main())
