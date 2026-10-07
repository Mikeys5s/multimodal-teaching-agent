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
    check('助手回复段数', stats['assistant_messages'], a_out)
    check('用户提问条数', stats['user_messages'], a_in)
    check('工具调用次数', stats['tool_calls'], a_call)
    check('工具返回条数', stats['tool_results'], a_res)

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
    check('jsonl 行数 = 各类型事件数之和', nlines,
          a_in + a_out + a_img + a_call + a_res + a_think_ne)
    check('jsonl 中 reasoning 条数', kinds.get('think', 0), a_think_ne)
    check('jsonl 中 tool 条数', kinds.get('tool', 0), a_call)
    check('jsonl 中 result 条数', kinds.get('result', 0), a_res)
    check('jsonl 中 user 条数', kinds.get('user', 0), a_in)
    check('jsonl 中 asst 条数', kinds.get('asst', 0), a_out)
    check('stats 登记的空思考数', stats['reasoning']['empty_skipped'], a_think - a_think_ne)
    check('jsonl 中 img 条数', kinds.get('img', 0), a_img)

    # ---- 4) 主文档可读性与完整性 ----
    print('\n[4] 主文档检查')
    md = io.open(os.path.join(outdir, '会话记录-完整版.md'), encoding='utf-8').read()
    check('用户块数', md.count('**👤 用户**'), a_in)
    check('助手块数 ≤ 用户块数', md.count('**🤖 助手**') <= a_in + 1, True,
          '（一轮可能没有可见助手输出）')
    check('system-reminder 残留', md.count('system-reminder'), 0)
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
    check('工具调用行展开合计', tot, a_call)

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
    check('HTML 含 system-reminder 残留', html.count('system-reminder'), 0)
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
