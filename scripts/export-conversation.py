# -*- coding: utf-8 -*-
"""
把 LearnBuddy 的会话记录（jsonl 事件流）整理成可读文档。

用法:
    python scripts/export-conversation.py <会话.jsonl> <输出目录> [--title "标题"]

产出:
    <输出目录>/会话记录-完整版.md      逐字全文，按日期分章
    <输出目录>/by-date/YYYY-MM-DD.md   按天分册
    <输出目录>/index.html              双击即开的浏览版（工具调用可折叠）
    <输出目录>/raw/conversation.jsonl  规范化全量事件（含工具输出原文）
    <输出目录>/raw/stats.json          统计数字

设计要点:
    - 流式读取，单遍解析；最后一行不完整（会话正在写入）时跳过，不报错
    - 用户消息里的 <system-reminder> 注入块整体剥离，只保留 <user_query> 正文
    - 助手回复按"轮次"重组：一次用户提问 ~ 下一次用户提问之间的全部输出
"""
import json
import os
import re
import sys
import datetime
import collections

# ---------- 解析 ----------

RE_SYSREM = re.compile(r'<system-reminder\b.*?</system-reminder>', re.S | re.I)
RE_USERQ = re.compile(r'<user_query>(.*?)</user_query>', re.S | re.I)
RE_IMGPATH = re.compile(r'<image_local_path>(.*?)</image_local_path>', re.S | re.I)
RE_LEFTOVER = re.compile(r'</?(system-reminder|automation_system_reminder|system_reminder)\b[^>]*>', re.I)

SKIP_TYPES = {'file-history-snapshot', 'resend-fork-notice'}


def ts_of(o):
    t = o.get('timestamp')
    try:
        return datetime.datetime.fromtimestamp(int(t) / 1000)
    except Exception:
        return None


def extract_user_text(raw):
    """从用户消息里取出真实输入。

    顺序至关重要：**必须先剥掉 <system-reminder> 注入块，再抽 <user_query>**。
    自动化任务的模板把 <user_query> 放在 <system-reminder> 闭合标签之后，
    但 reminder 内部也出现过字面量 <user_query>；若先抽后剥，非贪婪匹配会跨块
    把注入尾部并进用户正文（2026-09-26 实际踩到）。

    返回 (正文, 图片路径列表, 注入块数)
    """
    raw = raw or ''
    injections = len(RE_SYSREM.findall(raw))
    imgs = [p.strip() for p in RE_IMGPATH.findall(raw) if p.strip()]

    # ① 先剥系统注入
    clean = RE_SYSREM.sub('', raw)
    clean = RE_IMGPATH.sub('', clean)

    # ② 再抽用户原文
    qs = [q.strip() for q in RE_USERQ.findall(clean) if q.strip()]
    body = '\n\n'.join(qs).strip() if qs else clean.strip()

    # ③ 兜底：残留的注入标签壳一律清掉
    body = RE_LEFTOVER.sub('', body).strip()
    return body, imgs, injections


def short(s, n=120):
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n] + '…'


def summarize_call(name, args):
    """把一次工具调用压成一行人类可读摘要"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    g = args.get
    if name == 'Bash':
        return '`$ ' + short(g('command', ''), 200) + '`'
    if name == 'PowerShell':
        return '`PS> ' + short(g('command', ''), 200) + '`'
    if name == 'Read':
        return '读取 `%s`' % short(g('file_path', ''), 160)
    if name == 'Write':
        return '写入 `%s`（%d 字符）' % (short(g('file_path', ''), 160), len(str(g('content', ''))))
    if name == 'Edit':
        return '修改 `%s`' % short(g('file_path', ''), 160)
    if name == 'Glob':
        return '查找文件 `%s`' % short(g('pattern', ''), 160)
    if name == 'Grep':
        return '搜索 `%s`' % short(g('pattern', ''), 120)
    if name == 'present_files':
        f = g('files') or []
        return '展示 %d 个文件' % (len(f) if isinstance(f, list) else 0)
    if name == 'WebSearch':
        return '联网搜索：%s' % short(g('query', ''), 120)
    if name == 'WebFetch':
        return '抓取网页：%s' % short(g('url', ''), 160)
    if name == 'TaskCreate':
        return '建任务：%s' % short(g('subject', ''), 120)
    if name == 'TaskUpdate':
        return '更新任务 #%s → %s' % (g('taskId', '?'), g('status', ''))
    if name == 'Skill':
        return '调用技能：%s %s' % (g('skill', ''), short(g('args', ''), 80))
    if name == 'AskUserQuestion':
        qs = g('questions') or []
        q = qs[0].get('question', '') if isinstance(qs, list) and qs else ''
        return '向用户提问：%s' % short(q, 120)
    if name == 'Agent':
        return '派生子智能体：%s' % short(g('description', ''), 100)
    if name == 'TaskOutput':
        return '等待后台任务 `%s`' % g('task_id', '')
    if name == 'automation_update':
        return '定时任务 `%s`：%s' % (g('mode', ''), short(g('name', ''), 80))
    if name == 'show_widget':
        return '生成可视化：%s' % short(g('title', ''), 80)
    if name in ('read_me', 'TaskStop', 'TaskList', 'ToolSearch', 'ListMcpResources'):
        return ''
    keys = ', '.join(list(args.keys())[:4])
    return short(keys, 100)


def load_events(path):
    """单遍读取，返回统一事件列表（按文件内时序）"""
    events = []
    bad = 0
    n = 0
    reasoning_empty = 0
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                o = json.loads(line)
            except Exception:
                bad += 1          # 多数是会话正在写入导致的最后一行截断
                continue
            t = o.get('type')
            if t in SKIP_TYPES:
                continue
            dt = ts_of(o)

            if t == 'message':
                role = o.get('role')
                for it in (o.get('content') or []):
                    if not isinstance(it, dict):
                        continue
                    k = it.get('type')
                    if k == 'input_text':
                        body, imgs, inj = extract_user_text(it.get('text'))
                        if body or imgs:
                            events.append({'kind': 'user', 'ts': o.get('timestamp'), 'dt': dt,
                                           'text': body, 'images': imgs, 'injections': inj})
                    elif k == 'output_text':
                        txt = (it.get('text') or '').strip()
                        if txt:
                            events.append({'kind': 'asst', 'ts': o.get('timestamp'), 'dt': dt, 'text': txt})
                    elif k == 'image_blob_ref':
                        events.append({'kind': 'img', 'ts': o.get('timestamp'), 'dt': dt,
                                       'text': it.get('original_filename') or it.get('blob_id', '')[:12],
                                       'path': it.get('blob_path', '')})
                if role not in ('user', 'assistant') and (o.get('content') or o.get('message')):
                    # 兜底：其它角色的纯文本消息
                    m = o.get('message')
                    if isinstance(m, str) and m.strip():
                        events.append({'kind': 'asst' if role == 'assistant' else 'note',
                                       'ts': o.get('timestamp'), 'dt': dt, 'text': m.strip()})
            elif t == 'reasoning':
                rc = o.get('rawContent')
                if isinstance(rc, list):
                    rc = '\n'.join(
                        (x.get('text') or json.dumps(x, ensure_ascii=False)) if isinstance(x, dict) else str(x)
                        for x in rc)
                if not isinstance(rc, str):
                    rc = '' if rc is None else json.dumps(rc, ensure_ascii=False)
                rc = rc.strip()
                if rc:
                    events.append({'kind': 'think', 'ts': o.get('timestamp'), 'dt': dt, 'text': rc})
                else:
                    reasoning_empty += 1      # 空思考记录，不入档（数量在 stats 里显式登记）
            elif t == 'function_call':
                events.append({'kind': 'tool', 'ts': o.get('timestamp'), 'dt': dt,
                               'name': o.get('name') or '?',
                               'summary': summarize_call(o.get('name') or '', o.get('arguments')),
                               'callId': o.get('callId')})
            elif t == 'function_call_result':
                out = o.get('output')
                s = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
                events.append({'kind': 'result', 'ts': o.get('timestamp'), 'dt': dt,
                               'callId': o.get('callId'), 'status': o.get('status'),
                               'len': len(s or ''), 'text': s or ''})
    return events, {'lines': n, 'bad_json': bad, 'reasoning_empty': reasoning_empty}


def collapse_tools(items):
    """合并「连续且完全相同」的工具调用（如对同一文件连改 40 次 → 一条 ×40）。
    只在中间没有助手正文插入时合并，时序与信息量都不损失。"""
    out = []
    for it in items:
        if (it['kind'] == 'tool' and out and out[-1].get('kind') == 'tool'
                and out[-1].get('name') == it['name']
                and out[-1].get('summary') == it['summary']):
            out[-1]['count'] = out[-1].get('count', 1) + 1
            continue
        e = dict(it)
        e['count'] = 1
        out.append(e)
    return out


def build_turns(events):
    """按用户提问切分轮次"""
    turns = []
    cur = None
    for e in events:
        if e['kind'] == 'user':
            cur = {'user': e, 'items': []}
            turns.append(cur)
        else:
            if cur is None:
                cur = {'user': None, 'items': []}
                turns.append(cur)
            cur['items'].append(e)
    for t in turns:
        t['tool_calls_raw'] = sum(1 for x in t['items'] if x['kind'] == 'tool')
        # function_call_result 不进入可读文档（原文在 raw/conversation.jsonl），
        # 且它会插在同名工具调用之间，必须先剔除才能合并连续调用
        t['items'] = collapse_tools([x for x in t['items'] if x['kind'] != 'result'])
    return turns


# ---------- 渲染 Markdown ----------

def fmt_dt(dt, with_date=True):
    if not dt:
        return ''
    return dt.strftime('%Y-%m-%d %H:%M' if with_date else '%H:%M')


def render_turn_md(turn, idx, base_heading='##'):
    out = []
    u = turn['user']
    items = turn['items']
    if u:
        dt = u['dt']
        head = '%s 轮次 %d · %s' % (base_heading, idx, fmt_dt(dt))
        if u.get('images'):
            head += ' · 📎 %d 图' % len(u['images'])
        out.append(head)
        out.append('')
        out.append('**👤 用户**')
        out.append('')
        body = u['text'] or '（仅图片，无文字）'
        for ln in body.split('\n'):
            out.append('> ' + ln if ln.strip() else '>')
        out.append('')
        for p in u.get('images', []):
            out.append('> 📎 图片：`%s`' % os.path.basename(p))
        if u.get('images'):
            out.append('')
    visible = [it for it in items if it['kind'] in ('asst', 'tool', 'img', 'note')]
    if not visible:
        return out
    out.append('**🤖 助手**')
    out.append('')
    for it in items:
        k = it['kind']
        if k == 'asst':
            out.append(it['text'])
            out.append('')
        elif k == 'think':
            pass          # 模型的内部思考草稿不属于对话正文，见 raw/reasoning.md
        elif k == 'tool':
            s = it['summary']
            n = it.get('count', 1)
            out.append('- ⚙️ **%s**%s%s' % (it['name'], (' — ' + s) if s else '',
                                            ('（×%d）' % n) if n > 1 else ''))
        elif k == 'result':
            pass          # 结果原文不展开，见 raw/conversation.jsonl
        elif k == 'img':
            out.append('- 🖼️ 图片：`%s`' % it['text'])
        elif k == 'note':
            out.append(it['text'])
            out.append('')
    if items and items[-1]['kind'] == 'asst':
        pass
    out.append('')
    return out


def render_md(turns, title, meta_lines):
    out = ['# ' + title, '']
    for ln in meta_lines:
        out.append(ln)
    out.append('')
    out.append('---')
    out.append('')

    # 目录
    out.append('## 目录')
    out.append('')
    out.append('| # | 时间 | 用户提问（摘要） | 工具调用 |')
    out.append('|---|---|---|---|')
    for i, t in enumerate(turns, 1):
        u = t['user']
        if not u:
            continue
        dt = fmt_dt(u['dt'])
        summ = short(u['text'] or '（图片）', 60).replace('|', '\\|')
        ncalls = t.get('tool_calls_raw', 0)
        anchor = _anchor(i)
        out.append('| %d | %s | [%s](#%s) | %d |' % (i, dt, summ, anchor, ncalls))
    out.append('')

    # 正文按日期分章
    cur_date = None
    for i, t in enumerate(turns, 1):
        u = t['user']
        d = (u['dt'] if u else (t['items'][0]['dt'] if t['items'] else None))
        if d is None:
            continue
        ds = d.strftime('%Y-%m-%d')
        if ds != cur_date:
            cur_date = ds
            out.append('')
            out.append('# %s' % ds)
            out.append('')
        out.extend(render_turn_md(t, i, base_heading='##'))
    out.append('')
    return '\n'.join(out)


def _anchor(i):
    return 'turn-%d' % i


def render_datefile_md(date, turns, counts):
    title = 'LearnBuddy 会话记录 · %s' % date
    meta = ['> 工作日：%s　|　轮次 %d　|　助手回复 %d 段　|　工具调用 %d 次' %
            (date, counts['turns'], counts['asst'], counts['tool'])]
    out = ['# ' + title, '']
    out.extend(meta)
    out.append('')
    out.append('> 来源：LearnBuddy 会话记录（`~/.learnbuddy/projects/d-muti_tagent/9717e2f4-….jsonl`）')
    out.append('')
    out.append('---')
    out.append('')
    for i, t in enumerate(turns):
        out.extend(render_turn_md(t, i + 1, base_heading='##'))
    out.append('')
    return '\n'.join(out)


# ---------- 渲染 HTML ----------

def md_inline(s):
    s = (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    return s


def md_block(text):
    """极简 markdown → html：标题/引用/列表/表格/代码块/段落"""
    html = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith('```'):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            html.append('<pre><code>%s</code></pre>' % '\n'.join(buf).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            continue
        if s.startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s:|-]+\|$', lines[i + 1].strip()):
            head = [c.strip() for c in s.strip('|').split('|')]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            html.append('<table><thead><tr>' + ''.join('<th>%s</th>' % md_inline(c) for c in head) +
                        '</tr></thead><tbody>' +
                        ''.join('<tr>' + ''.join('<td>%s</td>' % md_inline(c) for c in r) + '</tr>' for r in rows) +
                        '</tbody></table>')
            continue
        if s.startswith('>'):
            buf = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            html.append('<blockquote>%s</blockquote>' % md_block('\n'.join(buf)))
            continue
        if re.match(r'^[-*]\s+', s):
            buf = []
            while i < len(lines) and re.match(r'^[-*]\s+', lines[i].strip()):
                buf.append(re.sub(r'^[-*]\s+', '', lines[i].strip()))
                i += 1
            html.append('<ul>' + ''.join('<li>%s</li>' % md_inline(x) for x in buf) + '</ul>')
            continue
        if re.match(r'^\d+\.\s+', s):
            buf = []
            while i < len(lines) and re.match(r'^\d+\.\s+', lines[i].strip()):
                buf.append(re.sub(r'^\d+\.\s+', '', lines[i].strip()))
                i += 1
            html.append('<ol>' + ''.join('<li>%s</li>' % md_inline(x) for x in buf) + '</ol>')
            continue
        m = re.match(r'^(#{1,4})\s+(.*)$', s)
        if m:
            lv = len(m.group(1))
            html.append('<h%d>%s</h%d>' % (lv, md_inline(m.group(2)), lv))
            i += 1
            continue
        # 段落：合并连续非空行
        buf = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,4}\s|[-*]\s|\d+\.\s|>|\||```)', lines[i].strip()):
            buf.append(lines[i])
            i += 1
        html.append('<p>%s</p>' % md_inline(' '.join(x.strip() for x in buf)))
    return '\n'.join(html)


def render_html(turns, title, meta):
    nav = []
    body = []
    cur_date = None
    for i, t in enumerate(turns, 1):
        u = t['user']
        d = (u['dt'] if u else (t['items'][0]['dt'] if t['items'] else None))
        if d is None:
            continue
        ds = d.strftime('%Y-%m-%d')
        if ds != cur_date:
            cur_date = ds
            body.append('<h2 class="date">%s</h2>' % ds)
        nav_extra = ' · 📎%d' % len(u['images']) if (u and u.get('images')) else ''
        nav.append('<a href="#turn-%d"><span class="nt">%s</span>%s<span class="nq">%s</span></a>' %
                   (i, fmt_dt(d, False), nav_extra,
                    (u['text'] if u else '（图片）')[:40].replace('<', '&lt;') or '（空）'))
        body.append('<section id="turn-%d">' % i)
        body.append('<div class="turn">')
        if u:
            body.append('<div class="user"><div class="who">👤 用户 · %s</div>' % fmt_dt(d))
            body.append(md_block(u['text'] or '（仅图片，无文字）'))
            for p in u.get('images', []):
                body.append('<p class="img">📎 图片：%s</p>' % os.path.basename(p).replace('<', '&lt;'))
            body.append('</div>')
        if any(it['kind'] in ('asst', 'tool', 'img', 'note') for it in t['items']):
            body.append('<div class="assistant"><div class="who">🤖 助手</div>')
            toolbuf = []
            for it in t['items']:
                k = it['kind']
                if k == 'asst':
                    if toolbuf:
                        body.append('<details class="tools"><summary>⚙️ %d 次工具调用</summary><ul>%s</ul></details>' % (len(toolbuf), ''.join(toolbuf)))
                        toolbuf = []
                    body.append(md_block(it['text']))
                elif k == 'tool':
                    n = it.get('count', 1)
                    toolbuf.append('<li><code>%s</code> %s%s</li>'
                                   % (it['name'], md_inline(it['summary']),
                                      ('<span class="cnt"> ×%d</span>' % n) if n > 1 else ''))
                elif k == 'think':
                    pass      # 内部思考草稿不入正文，见 raw/reasoning.md
                elif k == 'img':
                    body.append('<p class="img">🖼️ 图片：%s</p>' % md_inline(it['text']))
                elif k == 'note':
                    body.append(md_block(it['text']))
            if toolbuf:
                body.append('<details class="tools"><summary>⚙️ %d 次工具调用</summary><ul>%s</ul></details>' % (len(toolbuf), ''.join(toolbuf)))
            body.append('</div>')
        body.append('</div></section>')

    return HTML_TPL.format(title=title, meta='<br>'.join(meta), nav='\n'.join(nav), body='\n'.join(body))


HTML_TPL = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#ffffff; --fg:#1f2328; --muted:#6b7280; --line:#e5e7eb;
  --user-bg:#f0f6ff; --user-bd:#c7ddff; --asst-bg:#fafafa;
  --code-bg:#f3f4f6; --accent:#1a56db; --date:#0f172a;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.7 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
header {{ position:sticky; top:0; z-index:20; background:#fff;
  border-bottom:1px solid var(--line); padding:14px 24px; }}
header h1 {{ margin:0 0 4px; font-size:17px; }}
header .meta {{ color:var(--muted); font-size:12.5px; }}
.wrap {{ display:flex; align-items:flex-start; }}
nav {{ position:sticky; top:74px; width:290px; max-height:calc(100vh - 90px);
  overflow:auto; border-right:1px solid var(--line); padding:12px 8px 40px; flex:0 0 290px; }}
nav a {{ display:block; padding:6px 10px; color:var(--fg); text-decoration:none;
  border-radius:6px; font-size:12.5px; }}
nav a:hover {{ background:#f3f4f6; }}
nav .nt {{ color:var(--accent); font-weight:600; margin-right:6px; }}
nav .nq {{ display:block; color:var(--muted); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }}
main {{ flex:1; padding:20px 32px 120px; max-width:900px; }}
h2.date {{ font-size:15px; color:#fff; background:var(--date); display:inline-block;
  padding:4px 14px; border-radius:6px; margin:34px 0 14px; }}
.turn {{ margin:0 0 26px; }}
.user {{ background:var(--user-bg); border:1px solid var(--user-bd);
  border-radius:10px; padding:10px 14px; margin-bottom:10px; }}
.assistant {{ border-left:2px solid var(--line); padding-left:14px; }}
.who {{ font-size:12px; color:var(--muted); font-weight:600; margin-bottom:6px; }}
p {{ margin:6px 0; }}
blockquote {{ margin:4px 0; padding:2px 0 2px 12px; border-left:3px solid #d1d5db; color:#374151; }}
code {{ background:var(--code-bg); padding:1px 5px; border-radius:4px;
  font-family:"JetBrains Mono",Consolas,monospace; font-size:13px; }}
pre {{ background:var(--code-bg); padding:10px 12px; border-radius:8px; overflow:auto; }}
pre code {{ background:none; padding:0; }}
table {{ border-collapse:collapse; margin:10px 0; font-size:13.5px; width:100%; }}
th,td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; vertical-align:top; }}
th {{ background:#f9fafb; }}
details {{ margin:8px 0; }}
details.tools {{ font-size:12.5px; color:var(--muted); }}
details.tools summary {{ cursor:pointer; user-select:none; }}
details.tools ul {{ margin:6px 0 0; padding-left:20px; }}
.cnt {{ color:var(--accent); font-weight:600; }}
details.think {{ background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:6px 10px; }}
details.think summary {{ cursor:pointer; font-size:12.5px; color:#92400e; }}
.img {{ color:var(--muted); font-size:13px; }}
ul,ol {{ margin:6px 0; padding-left:24px; }}
li {{ margin:2px 0; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
</header>
<div class="wrap">
  <nav>{nav}</nav>
  <main>{body}</main>
</div>
</body>
</html>
'''


# ---------- 思考过程附录 ----------
# 背景（2026-09-26 实测）：reasoning 事件共 3194 条 / 584 万字符，其中 91% 的行是
# 流式输出的占位碎片（"OK." 15.9 万次、"Output." 6.7 万次、"Let me go." 4 万次…），
# 直接入档会把正文淹没（主文档曾因此膨胀到 8.7 MB / 87 万行）。
# 但 reasoning 里确有实质推理（56% 的事件含中文，如"单向依赖→上游错了下游必错"），
# 故单独成篇：主文档不收，此处过滤后收，原始文本留在 raw/conversation.jsonl。

import collections as _collections

TH_FREQ, TH_LEN = 5, 60


def build_reasoning_freq(events):
    freq = _collections.Counter()
    for e in events:
        if e['kind'] != 'think':
            continue
        for ln in e['text'].split('\n'):
            s = ln.strip()
            if s:
                freq[s] += 1
    return freq


def filter_reasoning(text, freq, th_freq=TH_FREQ, th_len=TH_LEN):
    """按行滤除高频重复的流式占位碎片；返回 (正文, 滤除行数, 保留行数)"""
    out, blank, dropped, kept = [], False, 0, 0
    for ln in text.split('\n'):
        s = ln.strip()
        if not s:
            if out and not blank:
                out.append('')
            blank = True
            continue
        if freq.get(s, 0) >= th_freq and len(s) <= th_len:
            dropped += 1
            continue
        out.append(s)
        blank = False
        kept += 1
    return '\n'.join(out).strip(), dropped, kept


def render_reasoning_md(events, freq, meta_lines):
    n_kinds = sum(1 for k, v in freq.items() if v >= TH_FREQ and len(k) <= TH_LEN)
    out = ['# 模型思考过程留痕（附录）', '']
    out.extend(meta_lines)
    out.append('')
    out.append('> ⚠️ **这不是对话内容。** 本文件是模型作答前的内部推理草稿，从会话记录中单独抽出，')
    out.append('> 便于核查"结论是怎么推出来的"。**对话正文见 `会话记录-完整版.md`。**')
    out.append('>')
    out.append('> 已滤除 **%d 类 / %d 行**高频重复的流式占位碎片'
               % (n_kinds, sum(v for k, v in freq.items() if v >= TH_FREQ and len(k) <= TH_LEN)))
    out.append('> （判据：同一行出现 ≥ %d 次且长度 ≤ %d 字符，如 `OK.` / `Let me go.` / `Emitting the Bash call.`）。'
               % (TH_FREQ, TH_LEN))
    out.append('> **未过滤的原文**见 `raw/conversation.jsonl` 中 `kind = "think"` 的行。')
    out.append('')
    out.append('---')
    out.append('')

    cur_date, n_ev, tot_chars = None, 0, 0
    for e in events:
        if e['kind'] != 'think':
            continue
        body, _, _ = filter_reasoning(e['text'], freq)
        if not body:
            continue
        ds = e['dt'].strftime('%Y-%m-%d') if e['dt'] else '（无时间戳）'
        if ds != cur_date:
            cur_date = ds
            out.append('## ' + ds)
            out.append('')
        out.append('### %s' % (e['dt'].strftime('%H:%M:%S') if e['dt'] else '—'))
        out.append('')
        out.append(body)
        out.append('')
        n_ev += 1
        tot_chars += len(body)
    out.append('')
    return '\n'.join(out), n_ev, tot_chars


# ---------- 主流程 ----------

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src = sys.argv[1]
    outdir = sys.argv[2]
    title = 'LearnBuddy 会话记录 · 析知 XiZhi（多模态教学智能体）'
    if '--title' in sys.argv:
        title = sys.argv[sys.argv.index('--title') + 1]

    print('读取：%s' % src)
    events, parse_info = load_events(src)
    turns = build_turns(events)

    n_user = sum(1 for e in events if e['kind'] == 'user')
    n_asst = sum(1 for e in events if e['kind'] == 'asst')
    n_tool = sum(1 for e in events if e['kind'] == 'tool')
    n_res = sum(1 for e in events if e['kind'] == 'result')
    n_inj = sum(e.get('injections', 0) for e in events if e['kind'] == 'user')
    n_leftover = sum(1 for e in events if e['kind'] == 'user'
                     and ('<system-reminder' in e['text'] or '<user_query>' in e['text']
                          or '</user_query>' in e['text']))
    dts = [e['dt'] for e in events if e.get('dt')]
    t0, t1 = (min(dts), max(dts)) if dts else (None, None)

    print('事件 %d（用户 %d / 助手 %d / 工具 %d / 结果 %d），轮次 %d'
          % (len(events), n_user, n_asst, n_tool, n_res, len(turns)))
    print('剥离系统注入块 %d 个；残留标签的用户消息 %d 条' % (n_inj, n_leftover))
    if n_leftover:
        print('  ⚠️ 存在残留，需检查 extract_user_text')
    assert n_leftover == 0, '用户正文里仍有注入标签残留'

    os.makedirs(outdir, exist_ok=True)
    os.makedirs(os.path.join(outdir, 'by-date'), exist_ok=True)
    os.makedirs(os.path.join(outdir, 'raw'), exist_ok=True)

    # 1) 规范化全量事件（含工具输出原文）
    rawp = os.path.join(outdir, 'raw', 'conversation.jsonl')
    with open(rawp, 'w', encoding='utf-8') as f:
        for i, e in enumerate(events, 1):
            rec = dict(e)
            if rec.get('dt'):
                rec['iso'] = rec['dt'].isoformat()
            rec.pop('dt', None)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # 2) 完整版 Markdown
    meta_lines = [
        '> **会话来源**：LearnBuddy 本地会话记录（`~/.learnbuddy/projects/d-muti_tagent/9717e2f4-d859-43ef-a704-b33ae7153a2c.jsonl`）',
        '> **时间跨度**：%s → %s（本地时间 GMT+8）' % (
            t0.strftime('%Y-%m-%d %H:%M') if t0 else '?',
            t1.strftime('%Y-%m-%d %H:%M') if t1 else '?'),
        '> **规模**：%d 轮对话 · 用户提问 %d 条 · 助手回复 %d 段 · 工具调用 %d 次' %
        (len(turns), n_user, n_asst, n_tool),
        '> **导出方式**：`python scripts/export-conversation.py`（原文逐字，仅剥离系统注入块）',
        '> **渲染规则**：工具调用只留一行摘要，其返回值原文不展开；连续且相同的调用合并为「×N」；',
        '> 模型思考草稿不属于对话内容，另见 `raw/reasoning.md`',
        '',
        '<!-- 说明：工具调用的返回值原文不在本文件展开，完整数据见 raw/conversation.jsonl -->',
    ]
    mdp = os.path.join(outdir, '会话记录-完整版.md')
    with open(mdp, 'w', encoding='utf-8') as f:
        f.write(render_md(turns, title, meta_lines))

    # 2b) 思考过程附录（滤除流式占位碎片后单独成篇）
    freq = build_reasoning_freq(events)
    rmeta = [
        '> **会话来源**：LearnBuddy 本地会话记录（`~/.learnbuddy/projects/d-muti_tagent/9717e2f4-d859-43ef-a704-b33ae7153a2c.jsonl`）',
        '> **时间跨度**：%s → %s（本地时间 GMT+8）' % (
            t0.strftime('%Y-%m-%d %H:%M') if t0 else '?',
            t1.strftime('%Y-%m-%d %H:%M') if t1 else '?'),
        '> **规模**：%d 轮对话 · 用户提问 %d 条 · 助手回复 %d 段 · 工具调用 %d 次' %
        (len(turns), n_user, n_asst, n_tool),
    ]
    rapp, r_ev, r_chars = render_reasoning_md(events, freq, rmeta)
    with open(os.path.join(outdir, 'raw', 'reasoning.md'), 'w', encoding='utf-8') as f:
        f.write(rapp)
    r_raw_ev = sum(1 for e in events if e['kind'] == 'think')
    r_raw_chars = sum(len(e['text']) for e in events if e['kind'] == 'think')
    r_drop_lines = sum(v for k, v in freq.items() if v >= TH_FREQ and len(k) <= TH_LEN)
    print('思考附录：非空 %d 条 / %d 字符 → 保留 %d 条 / %d 字符（滤除 %d 行占位碎片；另有 %d 条空思考未入档）'
          % (r_raw_ev, r_raw_chars, r_ev, r_chars, r_drop_lines, parse_info.get('reasoning_empty', 0)))

    # 3) 按天分册
    by_date = collections.OrderedDict()
    for t in turns:
        u = t['user']
        d = (u['dt'] if u else (t['items'][0]['dt'] if t['items'] else None))
        if d is None:
            continue
        by_date.setdefault(d.strftime('%Y-%m-%d'), []).append(t)
    for ds, ts in by_date.items():
        c = {
            'turns': len(ts),
            'asst': sum(1 for t in ts for x in t['items'] if x['kind'] == 'asst'),
            'tool': sum(t.get('tool_calls_raw', 0) for t in ts),
        }
        with open(os.path.join(outdir, 'by-date', ds + '.md'), 'w', encoding='utf-8') as f:
            f.write(render_datefile_md(ds, ts, c))

    # 4) HTML 浏览版
    sp = src.replace('\\', '/').split('/')[-1]
    meta = [
        '来源：LearnBuddy 本地会话记录 <code>%s</code>' % sp,
        '时间跨度：%s → %s（GMT+8）' % (
            t0.strftime('%Y-%m-%d %H:%M') if t0 else '?',
            t1.strftime('%Y-%m-%d %H:%M') if t1 else '?'),
        '规模：%d 轮 · 用户提问 %d 条 · 助手回复 %d 段 · 工具调用 %d 次' %
        (len(turns), n_user, n_asst, n_tool),
    ]
    with open(os.path.join(outdir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(render_html(turns, title, meta))

    # 5) 统计
    stats = {
        'source': src,
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'time_start': t0.isoformat() if t0 else None,
        'time_end': t1.isoformat() if t1 else None,
        'source_lines': parse_info['lines'],
        'bad_json_lines': parse_info['bad_json'],
        'turns': len(turns),
        'user_messages': n_user,
        'assistant_messages': n_asst,
        'tool_calls': n_tool,
        'tool_results': n_res,
        'system_injections_stripped': n_inj,
        'leftover_injection_tags': n_leftover,
        'reasoning': {
            'raw_events': r_raw_ev,
            'empty_skipped': parse_info.get('reasoning_empty', 0),
            'raw_chars': r_raw_chars,
            'kept_after_filter': r_ev,
            'kept_chars': r_chars,
            'dropped_placeholder_lines': r_drop_lines,
            'filter_rule': 'drop line if freq>=%d and len<=%d' % (TH_FREQ, TH_LEN),
        },
        'by_date': {ds: {'turns': len(ts),
                         'assistant': sum(1 for t in ts for x in t['items'] if x['kind'] == 'asst'),
                         'tools': sum(t.get('tool_calls_raw', 0) for t in ts)}
                    for ds, ts in by_date.items()},
    }
    with open(os.path.join(outdir, 'raw', 'stats.json'), 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    def sz(p):
        return os.path.getsize(p)
    print('\n产出：')
    print('  %-46s %8.1f KB' % (os.path.basename(mdp), sz(mdp) / 1024))
    print('  %-46s %8.1f KB' % ('index.html', sz(os.path.join(outdir, 'index.html')) / 1024))
    print('  %-46s %8.1f KB' % ('raw/reasoning.md（思考附录）', sz(os.path.join(outdir, 'raw', 'reasoning.md')) / 1024))
    print('  %-46s %8.1f KB' % ('raw/conversation.jsonl', sz(rawp) / 1024))
    print('  %-46s %8.1f KB' % ('raw/stats.json', sz(os.path.join(outdir, 'raw', 'stats.json')) / 1024))
    print('  by-date/ %d 个文件' % len(by_date))
    print('\n分日期：')
    for ds, c in stats['by_date'].items():
        print('  %s  轮次 %3d · 助手 %4d · 工具 %4d' % (ds, c['turns'], c['assistant'], c['tools']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
