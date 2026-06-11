#!/usr/bin/env python3
"""
gen_bench_report.py — build a visual HTML report for one agentic-DX bench sweep.

Given the START and END eval of a run (URL or bare id) on a promptfoo server, this:
  1. fetches the eval list, selects every eval in [start.createdAt, end.createdAt],
  2. pairs them into problems x {solve, verify} by parsing each eval's description,
  3. extracts per-agent rubric scores, static checks, costs, solver traces, and the
     verifier's per-bullet deductions,
  4. resolves each solve row's ATTACHED screenshot blobs to PNG bytes (content-addressed
     in the promptfoo media store) and embeds them under the matching problem chapter,
  5. renders a single self-contained HTML file (CSS + base64 inlined) with an in-page
     full-resolution lightbox.

It writes a COMPLETE, shippable report with data-derived narrative. Spots that benefit
from human/agent judgement are marked with `<!-- EDIT: ... -->` comments so the SKILL can
refine them (TL;DR insight, observations, deduction prose, captions). See SKILL.md.

Pure stdlib (urllib/json/base64) — no third-party deps. Reads blob bytes straight off disk.

Usage:
  python3 gen_bench_report.py \
      --start https://localhost:15500/eval/eval-Q5b-2026-06-11T06:02:17 \
      --end   eval-ayP-2026-06-11T07:27:00 \
      [--base-url http://localhost:15500] [--out docs/bench-reports/bench-results-<date>.html] \
      [--config-dir ~/.promptfoo] [--title "..."] [--lede "..."]
"""
import argparse, base64, html, json, os, re, sys, urllib.request

# --- agent palette: stable colors for known solvers, fallbacks for anything new ----
PREF_ORDER = ['codex', 'claude', 'claude-local-mcp', 'claude-no-skills']
PALETTE = {
    'codex': '#d97706',            # amber
    'claude': '#0d9488',           # teal
    'claude-local-mcp': '#7c3aed', # violet
    'claude-no-skills': '#64748b', # gray
}
FALLBACK = ['#2563eb', '#db2777', '#0891b2', '#ca8a04', '#9333ea', '#15803d']

PROBLEM_BLURB = {
    'basic_layout': 'responsive toolbar view',
    'basic_form': 'responsive onboarding form',
    'md_ui_spec': 'Employees CRUD from a markdown spec',
}
PROBLEM_ORDER = ['basic_layout', 'basic_form', 'md_ui_spec']


def strip_id(s):
    """Accept a full eval URL or a bare id; return the bare eval id."""
    s = s.strip().rstrip('/')
    if '/eval/' in s:
        s = s.split('/eval/', 1)[1]
    return s.split('?')[0].split('#')[0]


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def png_dims(data):
    """Width x height from a PNG header without any image library."""
    if len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    return 0, 0


def cls_of(agent):
    return re.sub(r'[^a-z0-9]+', '-', agent.lower()).strip('-')


def color_of(agent, assigned):
    if agent in PALETTE:
        return PALETTE[agent]
    if agent not in assigned:
        assigned[agent] = FALLBACK[len(assigned) % len(FALLBACK)]
    return assigned[agent]


def order_agents(agents):
    known = [a for a in PREF_ORDER if a in agents]
    rest = sorted(a for a in agents if a not in PREF_ORDER)
    return known + rest


def short_label(agent):
    """Compact label for tight chart rows."""
    return {'claude-no-skills': 'no-skills', 'claude-local-mcp': 'local-mcp'}.get(agent, agent)

# ----------------------------------------------------------------------------------
# 1. SELECT + FETCH
# ----------------------------------------------------------------------------------

def select_evals(base_url, start_id, end_id):
    data = fetch_json(f'{base_url}/api/results')['data']
    by_id = {e['evalId']: e for e in data}
    if start_id not in by_id or end_id not in by_id:
        missing = [x for x in (start_id, end_id) if x not in by_id]
        sys.exit(f'[gen] eval id(s) not found on server: {", ".join(missing)}')
    lo = min(by_id[start_id]['createdAt'], by_id[end_id]['createdAt'])
    hi = max(by_id[start_id]['createdAt'], by_id[end_id]['createdAt'])
    chosen = [e for e in data if lo <= e['createdAt'] <= hi]
    chosen.sort(key=lambda e: e['createdAt'])
    return chosen


PHASE_RE = re.compile(r'agentic-dx\s+([a-z0-9_]+)\s+[—-]', re.I)


def classify(desc):
    """-> (problem, phase) or (None, None) for non-bench evals in the range."""
    m = PHASE_RE.search(desc or '')
    if not m:
        return None, None
    problem = m.group(1)
    phase = 'verify' if ('PHASE 2' in desc or 'grade each solved' in desc) else 'solve'
    return problem, phase


def build_model(base_url, chosen):
    problems = {}
    skipped = []
    for e in chosen:
        prob, phase = classify(e.get('description', ''))
        if not prob:
            skipped.append(e['evalId'])
            continue
        detail = fetch_json(f"{base_url}/api/results/{e['evalId']}")['data']
        rows = detail['results']['results']
        p = problems.setdefault(prob, {'solve_eval': None, 'verify_eval': None,
                                       'solve': {}, 'verify': {}})
        p[f'{phase}_eval'] = e['evalId']
        for row in rows:
            agent = (row.get('provider') or {}).get('label') or '?'
            if phase == 'verify':
                agent = agent.replace('verify-', '')
                p['verify'][agent] = parse_verify(row)
            else:
                p['solve'][agent] = parse_solve(row)
    return problems, skipped


def parse_solve(row):
    ns = row.get('namedScores') or {}
    gr = row.get('gradingResult') or {}
    static_detail, fails = '', []
    for c in (gr.get('componentResults') or []):
        for ln in (c.get('reason') or '').splitlines():
            t = ln.strip()
            if t.startswith('Static source checks'):
                static_detail = t
            elif t.startswith('FAIL'):
                fails.append(re.sub(r'^FAIL\s+', '', t))
    resp = row.get('response') or {}
    err = resp.get('error')
    killed = (not row.get('success')) and bool(err)
    imgs = [im.get('blobRef', {}).get('hash') for im in (resp.get('images') or [])
            if im.get('blobRef', {}).get('hash')]
    return {
        'success': bool(row.get('success')), 'killed': killed, 'error': err,
        'static_score': row.get('score'), 'cost': row.get('cost') or 0.0,
        'static_detail': static_detail, 'fails': fails, 'img_hashes': imgs,
        'ns': {k: ns.get(k) for k in ('skill_calls', 'mcp_calls', 'tool_calls', 'tool_errors',
                                       'api_archaeology_calls', 'num_turns', 'solve_seconds',
                                       'cache_read_ktokens', 'output_tokens')},
    }


def parse_verify(row):
    out = (row.get('response') or {}).get('output')
    sections, deductions, tot, mx = [], [], 0, 0
    if isinstance(out, dict):
        for s in (out.get('criteria') or []):
            sc, m = s.get('score', 0), s.get('max-score', 0)
            tot += sc; mx += m
            sections.append((s.get('section'), sc, m))
            for b in s.get('bullets', []):
                if b.get('score', 1) < 1:
                    deductions.append({'section': s.get('section'), 'name': b.get('name'),
                                       'feedback': (b.get('feedback') or '').strip()})
    return {'success': bool(row.get('success')), 'norm': row.get('score') or 0.0,
            'cost': row.get('cost') or 0.0, 'raw': tot, 'max': mx,
            'sections': sections, 'deductions': deductions}


def load_blob(config_dir, h):
    f = os.path.join(config_dir, 'blobs', h[:2], h[2:4], h)
    if os.path.exists(f):
        with open(f, 'rb') as fh:
            return fh.read()
    return None

# ----------------------------------------------------------------------------------
# 2. RENDER
# ----------------------------------------------------------------------------------

CSS_BASE = """
  :root{--ink:#16202e;--muted:#5b6b7e;--line:#e3e8ef;--bg:#f6f8fb;--card:#fff;
    --indigo:#4f46e5;--green:#16a34a;--red:#dc2626;--amber:#b45309;
    --shadow:0 1px 2px rgba(16,32,46,.06),0 8px 24px rgba(16,32,46,.06)}
  *{box-sizing:border-box} html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
  code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  a{color:var(--indigo);text-decoration:none} a:hover{text-decoration:underline}
  nav.bar{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.86);backdrop-filter:saturate(180%) blur(10px);border-bottom:1px solid var(--line)}
  nav.bar .inner{max-width:1080px;margin:0 auto;padding:10px 22px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  nav.bar .brand{font-weight:700;margin-right:14px;letter-spacing:-.01em}
  nav.bar a{color:var(--muted);font-size:13.5px;padding:5px 10px;border-radius:7px}
  nav.bar a:hover{background:#eef1f6;color:var(--ink);text-decoration:none}
  .wrap{max-width:1080px;margin:0 auto;padding:0 22px}
  header.hero{padding:60px 22px 26px;max-width:1080px;margin:0 auto}
  header.hero .kicker{font:600 13px/1 ui-monospace,monospace;color:var(--indigo);letter-spacing:.08em;text-transform:uppercase}
  header.hero h1{font-size:clamp(30px,4.4vw,46px);line-height:1.08;letter-spacing:-.02em;margin:14px 0 8px}
  header.hero p.lede{font-size:19px;color:var(--muted);max-width:790px;margin:0}
  section{padding:34px 0;border-top:1px solid var(--line)} section:first-of-type{border-top:0}
  h2{font-size:26px;letter-spacing:-.015em;margin:0 0 6px;display:flex;align-items:center;gap:10px}
  h2 .num{font:700 14px/26px ui-monospace,monospace;color:#fff;background:var(--indigo);width:26px;height:26px;border-radius:7px;text-align:center;flex:none}
  h2 + .sub{color:var(--muted);margin:0 0 22px;font-size:16px} h3{font-size:17px;margin:22px 0 8px;letter-spacing:-.01em}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)} .pad{padding:20px 22px}
  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px} .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:820px){.grid3,.grid2{grid-template-columns:1fr}}
  .chip{display:inline-flex;align-items:center;gap:7px;font:600 12.5px/1 ui-monospace,monospace;padding:5px 10px;border-radius:999px;border:1px solid var(--line);background:#fff;white-space:nowrap}
  .dot{width:9px;height:9px;border-radius:50%;flex:none} .legend{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:18px 20px}
  .stat .big{font-size:32px;font-weight:800;letter-spacing:-.02em;line-height:1.06} .stat .lbl{color:var(--muted);font-size:13.5px;margin-top:4px} .stat .sm{font-size:13px;color:var(--muted);margin-top:8px}
  .chartcard{padding:18px 22px 8px} .chart-title{font-weight:700;font-size:15px;margin:0 0 2px} .chart-sub{color:var(--muted);font-size:13px;margin:0 0 14px}
  .row{display:grid;grid-template-columns:128px 1fr;align-items:center;gap:12px;margin:9px 0}
  .row .name{font:600 13px/1.3 ui-monospace,monospace;text-align:right;color:var(--muted)}
  .track{position:relative;background:#f0f3f7;border-radius:8px;height:30px;overflow:hidden}
  .fill{height:100%;border-radius:8px;display:flex;align-items:center;justify-content:flex-end;padding-right:10px;color:#fff;font:700 13px/1 ui-monospace,monospace;min-width:44px;transition:width .6s ease}
  .fill.dead{background:repeating-linear-gradient(45deg,#f0d3d3 0 7px,#f7e3e3 7px 14px);color:var(--red);justify-content:flex-start;padding-left:10px;border:1px dashed #e2a8a8}
  .floor{position:absolute;top:-4px;bottom:-4px;width:2px;background:repeating-linear-gradient(180deg,var(--red) 0 4px,transparent 4px 8px);z-index:2}
  .axis{grid-column:2;display:flex;justify-content:space-between;font:11px/1 ui-monospace,monospace;color:#9aa7b5;margin-top:2px}
  table{width:100%;border-collapse:collapse;font-size:14px} th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}
  th{font:600 12px/1 ui-monospace,monospace;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
  td.n,th.n{text-align:right;font-family:ui-monospace,monospace} tbody tr:last-child td{border-bottom:0} .best{font-weight:800;color:var(--ink)}
  .ded{border-left:3px solid var(--amber);background:#fffaf0;border-radius:0 10px 10px 0;padding:12px 16px;margin:10px 0}
  .ded.perfect{border-color:var(--green);background:#f1faf3} .ded .who{font:700 12.5px/1 ui-monospace,monospace;display:inline-flex;align-items:center;gap:6px}
  .ded .pts{font-weight:800;color:var(--red);margin-left:6px} .ded p{margin:6px 0 0;font-size:14px;color:#3a4656}
  ul.clean{margin:6px 0;padding-left:20px} ul.clean li{margin:7px 0}
  .note{background:#fff8e6;border:1px solid #f3e3b3;border-radius:12px;padding:14px 18px;font-size:14.5px;color:#5c4a12} .note b{color:#7a5d00}
  .note.warn{background:#fdecec;border-color:#f3c0c0;color:#7a1f1f} .note.warn b{color:#9a1212}
  .mini{font-size:13px;color:var(--muted)} footer{padding:30px 22px 60px;max-width:1080px;margin:0 auto;color:var(--muted);font-size:13px}
  .shotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
  .shot{margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden;display:flex;flex-direction:column}
  .shot-head{display:flex;align-items:center;gap:8px;padding:11px 13px;border-bottom:1px solid var(--line);flex-wrap:wrap}
  .shot-head .dims{font:11px/1 ui-monospace,monospace;color:#9aa7b5;margin-left:auto}
  .frame{background:#eef1f5;display:flex;justify-content:center;align-items:flex-start} .frame img{width:100%;height:auto;display:block} .frame.tall{max-height:440px;overflow:auto}
  figcaption{padding:11px 14px;font-size:13px;color:#3a4656;border-top:1px solid var(--line)}
  #lightbox{display:none;position:fixed;inset:0;z-index:200;background:rgba(8,12,18,.93);overflow:auto;cursor:zoom-out;padding:24px 0}
  #lightbox img{display:block;margin:auto;max-width:none;height:auto;box-shadow:0 12px 60px rgba(0,0,0,.6);border-radius:6px}
  #lightbox .lb-close{position:fixed;top:12px;right:18px;z-index:201;color:#fff;font:700 24px/1 system-ui,sans-serif;background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.25);border-radius:10px;width:42px;height:42px;cursor:pointer;display:flex;align-items:center;justify-content:center}
  #lightbox .lb-close:hover{background:rgba(0,0,0,.65)}
  #lightbox .lb-hint{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);z-index:201;color:#cdd6e0;font:12px/1 ui-monospace,monospace;background:rgba(0,0,0,.45);padding:7px 13px;border-radius:999px;border:1px solid rgba(255,255,255,.15)}
"""

LIGHTBOX_HTML = """
<div id="lightbox" onclick="lbClose()">
  <button class="lb-close" type="button" aria-label="Close" onclick="lbClose()">&times;</button>
  <img id="lightbox-img" alt="full resolution screenshot">
  <div class="lb-hint">full resolution &middot; scroll to pan &middot; click anywhere or press Esc to close</div>
</div>
<script>
  function lb(s){var o=document.getElementById('lightbox');document.getElementById('lightbox-img').src=s;o.style.display='block';o.scrollTop=0;document.body.style.overflow='hidden';}
  function lbClose(){var o=document.getElementById('lightbox');o.style.display='none';document.getElementById('lightbox-img').removeAttribute('src');document.body.style.overflow='';}
  document.addEventListener('keydown',function(e){if(e.key==='Escape')lbClose();});
</script>
"""


def fmt_cost(c):
    return '—' if c is None else f'${c:.2f}'


def fmt_num(v):
    if v is None:
        return '—'
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def agent_css(agents, assigned):
    out = []
    for a in agents:
        cls, col = cls_of(a), color_of(a, assigned)
        out.append(f'  .c-{cls}{{color:{col}}} .d-{cls}{{background:{col}}} .fill-{cls}{{background:{col}}}')
    return '\n'.join(out)


def chip(agent, assigned, label=None):
    cls = cls_of(agent)
    return f'<span class="chip c-{cls}"><span class="dot d-{cls}"></span>{html.escape(label or agent)}</span>'


def render(model, meta, assigned):
    problems = model['problems']
    agents = model['agents']
    P = [p for p in PROBLEM_ORDER if p in problems] + [p for p in problems if p not in PROBLEM_ORDER]
    e = html.escape

    parts = []
    parts.append(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(meta["title"])}</title>
<style>{CSS_BASE}
{agent_css(agents, assigned)}
</style></head><body>''')

    # nav
    nav = ['<a href="#tldr">TL;DR</a>', '<a href="#rubric">Rubric</a>', '<a href="#cost">Cost</a>']
    nav += [f'<a href="#p-{p}">{p}</a>' for p in P]
    nav += ['<a href="#obs">Observations</a>', '<a href="#caveats">Caveats</a>']
    parts.append(f'<nav class="bar"><div class="inner"><span class="brand">agentic-DX bench</span>{"".join(nav)}</div></nav>')

    # hero
    legend = ''.join(chip(a, assigned, meta['agent_legend'].get(a, a)) for a in agents)
    parts.append(f'''<header class="hero"><div class="kicker">benchmark report &middot; {e(meta["date"])}</div>
<h1>{e(meta["headline_h1"])}</h1><p class="lede">{meta["lede"]}</p>
<div class="legend" style="margin-top:22px">{legend}</div></header><div class="wrap">''')

    # ---- TL;DR ----
    parts.append('<section id="tldr"><h2><span class="num">1</span> TL;DR</h2>')
    parts.append(f'<p class="sub">Eval range: <a href="{meta["start_url"]}"><code>{e(meta["start_id"])}</code></a> '
                 f'&rarr; <a href="{meta["end_url"]}"><code>{e(meta["end_id"])}</code></a> on <code>{e(meta["base_url"])}</code>.</p>')
    parts.append('<div class="grid3" style="margin-bottom:16px">')
    for big, lbl, sm in meta['tldr_stats']:
        parts.append(f'<div class="stat"><div class="big">{big}</div><div class="lbl">{lbl}</div><div class="sm">{sm}</div></div>')
    parts.append('</div>')
    parts.append('<div class="card pad"><!-- EDIT: refine these into the run\'s real story --><ul class="clean">')
    for b in meta['tldr_bullets']:
        parts.append(f'<li>{b}</li>')
    parts.append('</ul></div></section>')

    # ---- Rubric ----
    parts.append('<section id="rubric"><h2><span class="num">2</span> Rubric scores</h2>')
    parts.append('<p class="sub">Phase 2 &mdash; normalized fraction of each problem\'s rubric max. Bars are full 0&ndash;100%; the dashed line marks the <code>0.60</code> pass floor.</p>')
    parts.append('<div class="grid3">')
    for p in P:
        v = problems[p]['verify']
        parts.append(f'<div class="card chartcard"><p class="chart-title">{p} <span class="mini">&middot; max {max((d["max"] for d in v.values()), default="?")}</span></p>'
                     f'<p class="chart-sub">{PROBLEM_BLURB.get(p, "")}</p>')
        for a in order_agents(list(v.keys())):
            d = v[a]
            w = round(d['norm'] * 100, 1)
            parts.append(f'<div class="row"><div class="name c-{cls_of(a)}">{e(short_label(a))}</div>'
                         f'<div class="track"><div class="floor" style="left:60%"></div>'
                         f'<div class="fill fill-{cls_of(a)}" style="width:{w}%">{d["raw"]}/{d["max"]}</div></div></div>')
        parts.append('<div class="axis"><span>0%</span><span>100%</span></div></div>')
    parts.append('</div>')
    if meta['self_grading_note']:
        parts.append(f'<div class="note warn" style="margin-top:18px">{meta["self_grading_note"]}</div>')
    # static table
    parts.append('<h3>Static source checks (phase 1 &mdash; idiom gate)</h3><div class="card pad" style="padding-top:6px;padding-bottom:6px"><table><thead><tr><th>Problem</th>')
    for a in agents:
        parts.append(f'<th class="n">{e(short_label(a))}</th>')
    parts.append('<th>what slipped</th></tr></thead><tbody>')
    for p in P:
        s = problems[p]['solve']
        parts.append(f'<tr><td><code>{p}</code></td>')
        slip = set()
        for a in agents:
            d = s.get(a)
            if not d:
                parts.append('<td class="n">&middot;</td>')
            elif d['killed']:
                parts.append('<td class="n" style="color:var(--red)">killed</td>')
            else:
                sd = d['static_detail']
                m = re.search(r'\((\d+)/(\d+)', sd)
                parts.append(f'<td class="n">{m.group(1)+"/"+m.group(2) if m else fmt_num(d["static_score"])}</td>')
                slip.update(d['fails'])
        parts.append(f'<td class="mini">{e(", ".join(sorted(slip))) if slip else "clean sweep"}</td></tr>')
    parts.append('</tbody></table></div><p class="mini">Only the <code>@Route</code> check gates pass/fail; the rest are deductions.</p></section>')

    # ---- Cost ----
    parts.append('<section id="cost"><h2><span class="num">3</span> Cost</h2>')
    all_solve = [d['cost'] for p in P for d in problems[p]['solve'].values() if d['cost']]
    scale = max(all_solve, default=1)
    import math
    scale = max(1, math.ceil(scale))
    parts.append(f'<p class="sub">Solve cost per problem (USD, shared 0 &rarr; ${scale} scale). The <code>cost</code> column is accurate (Agent SDK / Codex <code>total_cost_usd</code>).</p>')
    parts.append('<div class="grid2"><div class="card chartcard"><p class="chart-title">Solve cost per problem</p>'
                 f'<p class="chart-sub">USD &middot; same scale across all rows &middot; 100% = ${scale}</p>')
    for p in P:
        s = problems[p]['solve']
        parts.append(f'<div style="margin:8px 0 2px"><span class="mini" style="font-weight:700">{p}</span></div>')
        for a in order_agents(list(s.keys())):
            d = s[a]
            if d['killed']:
                parts.append(f'<div class="row"><div class="name c-{cls_of(a)}">{e(short_label(a))}</div>'
                             f'<div class="track"><div class="fill dead" style="width:34%">killed &middot; $0 recorded</div></div></div>')
            else:
                w = round(d['cost'] / scale * 100, 1)
                parts.append(f'<div class="row"><div class="name c-{cls_of(a)}">{e(short_label(a))}</div>'
                             f'<div class="track"><div class="fill fill-{cls_of(a)}" style="width:{w}%">${d["cost"]:.2f}</div></div></div>')
    parts.append(f'<div class="axis"><span>$0</span><span>${scale}</span></div></div>')
    # totals table
    parts.append('<div><div class="card pad"><p class="chart-title" style="margin-bottom:12px">Total by agent <span class="mini">(solve + verify)</span></p><table><thead><tr><th>Agent</th><th class="n">solve</th><th class="n">verify</th><th class="n">total</th></tr></thead><tbody>')
    for a in agents:
        sv = sum(problems[p]['solve'].get(a, {}).get('cost', 0) for p in P)
        vf = sum(problems[p]['verify'].get(a, {}).get('cost', 0) for p in P)
        parts.append(f'<tr><td>{chip(a, assigned, short_label(a))}</td><td class="n">${sv:.2f}</td><td class="n">${vf:.2f}</td><td class="n best">${sv+vf:.2f}</td></tr>')
    grand = sum(problems[p][ph].get(a, {}).get('cost', 0) for p in P for ph in ('solve', 'verify') for a in agents)
    parts.append(f'</tbody></table></div><div class="stat" style="margin-top:16px"><div class="big">${grand:.2f}</div><div class="lbl">total cost for the sweep</div><div class="sm"><!-- EDIT: cost takeaway --></div></div></div></div></section>')

    # ---- per-problem chapters ----
    for i, p in enumerate(P, start=4):
        parts.append(render_problem(i, p, problems[p], agents, assigned, meta))

    # ---- Observations ----
    parts.append(f'<section id="obs"><h2><span class="num">{4+len(P)}</span> Cross-cutting observations</h2><div class="grid2">')
    for title, body in meta['observations']:
        parts.append(f'<div class="card pad"><h3 style="margin-top:0">{title}</h3><p style="margin:0;font-size:14.5px">{body}</p></div>')
    parts.append('</div></section>')

    # ---- Caveats ----
    parts.append(f'<section id="caveats"><h2><span class="num">{5+len(P)}</span> Caveats &amp; data gaps</h2><div class="card pad"><ul class="clean">')
    for c in meta['caveats']:
        parts.append(f'<li>{c}</li>')
    parts.append('</ul></div></section>')

    parts.append(f'</div><footer>Source: promptfoo evals <code>{e(meta["start_id"])}</code> &hellip; <code>{e(meta["end_id"])}</code> on <code>{e(meta["base_url"])}</code>, {e(meta["date"])} &middot; generated by the <code>bench-report</code> skill from the eval JSON.</footer>')
    parts.append(LIGHTBOX_HTML)
    parts.append('</body></html>')
    return '\n'.join(parts)


SOLVE_COLS = [('static', 'static_score'), ('cost', None), ('wall', 'solve_seconds'),
              ('turns', 'num_turns'), ('mcp', 'mcp_calls'), ('tool (err)', None),
              ('api-arch', 'api_archaeology_calls'), ('cache-rd', 'cache_read_ktokens')]


def render_problem(num, p, data, agents, assigned, meta):
    e = html.escape
    out = [f'<section id="p-{p}"><h2><span class="num">{num}</span> {p} '
           f'<span class="mini" style="font-weight:400;font-size:15px">&middot; {PROBLEM_BLURB.get(p, "")}</span></h2>']
    v = data['verify']
    rank = ' &middot; '.join(f'<span class="c-{cls_of(a)}">{short_label(a)} {v[a]["raw"]}</span>'
                            for a in sorted(v, key=lambda a: -v[a]['raw']))
    out.append(f'<p class="sub">Rubric: {rank}. <!-- EDIT: one-line framing for this problem --></p>')

    # solve trace table
    out.append('<div class="card pad" style="margin-bottom:16px"><table><thead><tr><th>solver</th>')
    for h, _ in SOLVE_COLS:
        out.append(f'<th class="n">{h}</th>')
    out.append('</tr></thead><tbody>')
    for a in order_agents(list(data['solve'].keys())):
        d = data['solve'][a]
        if d['killed']:
            why = (d['error'] or '').strip()
            out.append(f'<tr><td><span class="c-{cls_of(a)}">{e(short_label(a))}</span></td>'
                       f'<td class="n" colspan="{len(SOLVE_COLS)}" style="color:var(--red)">row killed &mdash; {e(why[:90])} &middot; no phase-1 metrics</td></tr>')
            continue
        out.append(f'<tr><td><span class="c-{cls_of(a)}">{e(short_label(a))}</span></td>')
        for h, key in SOLVE_COLS:
            if h == 'static':
                out.append(f'<td class="n">{fmt_num(d["static_score"]) if not isinstance(d["static_score"],float) else round(d["static_score"],3)}</td>')
            elif h == 'cost':
                out.append(f'<td class="n">{fmt_cost(d["cost"])}</td>')
            elif h == 'tool (err)':
                tc, te = d['ns'].get('tool_calls'), d['ns'].get('tool_errors')
                out.append(f'<td class="n">{fmt_num(tc)}{"" if te is None else f" ({fmt_num(te)})"}</td>')
            elif h == 'wall':
                w = d['ns'].get('solve_seconds')
                out.append(f'<td class="n">{("" if w is None else str(round(w))+"s") or "—"}</td>')
            elif h == 'cache-rd':
                c = d['ns'].get('cache_read_ktokens')
                out.append(f'<td class="n">{"—" if c is None else str(round(c))+"k"}</td>')
            else:
                out.append(f'<td class="n">{fmt_num(d["ns"].get(key))}</td>')
        out.append('</tr>')
    out.append('</tbody></table></div>')

    # deduction callouts
    any_ded = False
    for a in order_agents(list(v.keys())):
        d = v[a]
        cls = cls_of(a)
        if not d['deductions']:
            out.append(f'<div class="ded perfect"><span class="who" style="color:var(--green)">&check; {e(short_label(a))}</span>'
                       f'<span class="pts" style="color:var(--green)">{d["raw"]}/{d["max"]}</span>'
                       f'<p>No rubric deductions. <!-- EDIT: note anything notable --></p></div>')
            continue
        any_ded = True
        lost = d['max'] - d['raw']
        items = ''.join(f'<li><b>{e(x["section"])}:</b> {e(x["name"])} &mdash; <span class="mini">{e(x["feedback"][:240])}</span></li>'
                        for x in d['deductions'])
        out.append(f'<div class="ded" style="border-color:{color_of(a, assigned)}">'
                   f'<span class="who c-{cls}"><span class="dot d-{cls}"></span>{e(short_label(a))}</span>'
                   f'<span class="pts">&minus;{lost}</span><!-- EDIT: turn the bullets below into prose -->'
                   f'<ul class="clean" style="margin-top:8px">{items}</ul></div>')

    # screenshots under the chapter
    shots = data.get('shots', [])
    out.append('<h3 style="margin-top:26px">Screenshots</h3>')
    if shots:
        out.append('<p class="mini">Solver captures attached to the solve eval &middot; click for full resolution.</p><div class="shotgrid">')
        for sh in shots:
            tall = 'tall' if sh['h'] > sh['w'] * 1.4 else ''
            out.append(f'<figure class="shot"><div class="shot-head">{chip(sh["agent"], assigned, short_label(sh["agent"]))}'
                       f'<span class="dims">{sh["w"]}&times;{sh["h"]}</span></div>'
                       f'<div class="frame {tall}"><img loading="lazy" src="{sh["uri"]}" alt="{e(sh["agent"])} {sh["w"]}x{sh["h"]}" '
                       f'onclick="lb(this.src)" style="cursor:zoom-in" title="click for full resolution"></div>'
                       f'<figcaption><!-- EDIT: caption --> {e(short_label(sh["agent"]))} result</figcaption></figure>')
        out.append('</div>')
    else:
        out.append('<p class="mini">No solver screenshots were attached for this problem in this run.</p>')

    out.append('</section>')
    return '\n'.join(out)

# ----------------------------------------------------------------------------------
# 3. AUTO-NARRATIVE (data-derived defaults; the SKILL refines the EDIT spots)
# ----------------------------------------------------------------------------------

def build_meta(model, args):
    problems = model['problems']
    agents = model['agents']
    P = [p for p in PROBLEM_ORDER if p in problems] + [p for p in problems if p not in PROBLEM_ORDER]
    date = next((re.search(r'(\d{4}-\d{2}-\d{2})', x).group(1)
                 for x in (args.start_id, args.end_id) if re.search(r'(\d{4}-\d{2}-\d{2})', x)), 'run')

    # rows passed / total
    total = sum(len(problems[p]['solve']) + len(problems[p]['verify']) for p in P)
    passed = sum(1 for p in P for ph in ('solve', 'verify') for d in problems[p][ph].values() if d['success'])
    killed = [(p, a) for p in P for a, d in problems[p]['solve'].items() if d['killed']]
    grand = sum(problems[p][ph].get(a, {}).get('cost', 0) for p in P for ph in ('solve', 'verify') for a in agents)
    has_codex = 'codex' in agents
    self_grading = not has_codex  # without a non-Claude solver, every grade is Claude-on-Claude

    # systematic bug: a rubric section lost by EVERY agent on a problem
    systematic = []
    for p in P:
        v = problems[p]['verify']
        if len(v) < 2:
            continue
        lost_sections = [set(x['section'] for x in d['deductions']) for d in v.values()]
        common = set.intersection(*lost_sections) if lost_sections else set()
        for sec in common:
            systematic.append((p, sec))

    headline_h1 = args.title or f'agentic-DX bench — {date} run'  # literal em-dash; it's html.escape()d on render
    tldr_stats = [
        (f'{passed} / {total}', 'rows passed (solve + verify)', 'one killed row = harness hang, see chapters' if killed else 'no failures'),
        (f'${grand:.2f}', 'total cost for the sweep', f'{len(agents)} solvers &times; {len(P)} problems &times; 2 phases'),
        ('', '', ''),  # third stat is an EDIT slot for the headline insight
    ]
    tldr_stats[2] = ('<!-- EDIT -->', 'headline insight', 'replace with the run\'s key finding')

    tldr_bullets = ['<!-- EDIT: replace these auto-derived bullets with the real story -->']
    for p in P:
        v = problems[p]['verify']
        if v:
            best = max(v, key=lambda a: v[a]['raw'])
            spread = ', '.join('%s %d' % (short_label(a), v[a]['raw']) for a in order_agents(list(v.keys())))
            tldr_bullets.append(f'<b>{p}:</b> {short_label(best)} led at {v[best]["raw"]}/{v[best]["max"]} ({spread}).')
    for p, sec in systematic:
        tldr_bullets.append(f'<b>Systematic on {p}:</b> every agent lost points in <em>{sec}</em> &mdash; likely a benchmark-level cause, not an agent gap.')
    if killed:
        for p, a in killed:
            vd = problems[p]['verify'].get(a)
            extra = f' &mdash; yet phase 2 graded that workspace {vd["raw"]}/{vd["max"]}, so the app built fine' if vd else ''
            tldr_bullets.append(f'<b>{short_label(a)} / {p}</b> row was killed (SDK hang / SIGTERM){extra}.')

    self_note = ''
    if self_grading:
        self_note = ('&#9888; <b>Self-grading is total this run.</b> With no non-Claude solver, every solver <em>and</em> '
                     'verifier is a Claude agent, so all rubric grades are Claude judging Claude. The rubric is mostly '
                     'measurement-based (Playwright-observed), which limits bias &mdash; but take absolute scores with that in mind.')
    elif has_codex:
        self_note = ('&#9888; <b>Self-grading caveat.</b> The Claude solver rows are graded by a Claude verifier (Claude judging '
                     'Claude). The <code>codex</code> rows are cross-graded and are the cleaner comparison.')

    observations = [('<!-- EDIT -->Add the run\'s real insights', 'Replace this card with cross-cutting findings &mdash; e.g. what the agent comparison shows, recurring bugs, cost/quality tradeoffs.')]
    for p, sec in systematic[:2]:
        observations.append((f'Systematic deduction on {p}', f'Every agent lost <em>{sec}</em> points on <code>{p}</code> &mdash; investigate the task/skeleton before reading the spread as an agent skill gap.'))

    caveats = []
    if killed:
        caveats.append('<b>Killed row(s).</b> A solve row exited via SIGTERM (the agent-SDK hang: work finished but the process never exited, so the timeout reaped it). Its phase-1 cost/trace are lost; the workspace was still graded in phase 2. Don\'t read that eval\'s pass-rate as a solver failure.')
    if self_grading:
        caveats.append('<b>Self-grading is total this run</b> (no non-Claude solver) &mdash; every grade is Claude-on-Claude.')
    elif has_codex:
        caveats.append('<b>Self-grading</b> applies to the Claude solver rows; the Codex rows are cross-graded.')
    caveats.append('<b>Token columns understate throughput</b> by design (cache read/creation dropped from the top-level total); the <code>cache-rd</code> figures are the real numbers from <code>metadata.modelUsage</code>. Use <code>cost</code> for efficiency.')
    caveats.append('<b>n = 1 per cell.</b> Treat &plusmn;1&ndash;2 rubric points as noise, not a ranking. Re-run with <code>REPEAT=N</code> for variance.')

    return {
        'title': args.title or f'agentic-DX bench — {date} results',
        'date': date, 'headline_h1': headline_h1,
        'lede': args.lede or ('<!-- EDIT: one-paragraph framing of what this run tested -->'
                              f' A solve&rarr;verify sweep of {len(P)} Vaadin problems by {len(agents)} solver(s), graded against each problem\'s rubric.'),
        'base_url': args.base_url, 'start_id': args.start_id, 'end_id': args.end_id,
        'start_url': f'{args.base_url}/eval/{args.start_id}', 'end_url': f'{args.base_url}/eval/{args.end_id}',
        'agent_legend': {a: a for a in agents},
        'tldr_stats': tldr_stats, 'tldr_bullets': tldr_bullets,
        'self_grading_note': self_note, 'observations': observations, 'caveats': caveats,
    }

# ----------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='Generate a visual HTML bench report from an eval range.')
    ap.add_argument('--start', required=True, help='start eval URL or id')
    ap.add_argument('--end', required=True, help='end eval URL or id')
    ap.add_argument('--base-url', default='http://localhost:15500')
    ap.add_argument('--config-dir', default=os.path.expanduser('~/.promptfoo'), help='promptfoo config dir (for blob screenshots)')
    ap.add_argument('--out', default=None, help='output HTML path (default docs/bench-reports/bench-results-<date>.html)')
    ap.add_argument('--title', default=None)
    ap.add_argument('--lede', default=None)
    args = ap.parse_args()

    args.base_url = args.base_url.rstrip('/')
    args.start_id = strip_id(args.start)
    args.end_id = strip_id(args.end)

    print(f'[gen] selecting evals {args.start_id} .. {args.end_id} on {args.base_url}', file=sys.stderr)
    chosen = select_evals(args.base_url, args.start_id, args.end_id)
    problems, skipped = build_model(args.base_url, chosen)
    if skipped:
        print(f'[gen] skipped {len(skipped)} non-bench eval(s) in range: {", ".join(skipped)}', file=sys.stderr)
    if not problems:
        sys.exit('[gen] no agentic-dx bench evals found in range')

    agents = order_agents(list({a for p in problems.values() for a in p['solve']} |
                               {a for p in problems.values() for a in p['verify']}))

    # resolve attached screenshots -> base64, grouped under each problem
    n_shots = 0
    for p, pdata in problems.items():
        shots = []
        for a in order_agents(list(pdata['solve'].keys())):
            for h in pdata['solve'][a]['img_hashes']:
                raw = load_blob(args.config_dir, h)
                if not raw:
                    print(f'[gen]   blob {h[:12]} missing on disk ({p}/{a}) — skipping', file=sys.stderr)
                    continue
                w, hh = png_dims(raw)
                shots.append({'agent': a, 'w': w, 'h': hh,
                              'uri': 'data:image/png;base64,' + base64.b64encode(raw).decode()})
                n_shots += 1
        pdata['shots'] = shots

    model = {'problems': problems, 'agents': agents}
    assigned = {}
    meta = build_meta(model, args)
    htmlout = render(model, meta, assigned)

    out = args.out or f'docs/bench-reports/bench-results-{meta["date"]}.html'
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(htmlout)

    pj = ', '.join(f'{p}({len(problems[p]["solve"])}s/{len(problems[p]["verify"])}v)' for p in problems)
    print(f'[gen] wrote {out}  ({len(htmlout)//1024} KB, {n_shots} screenshots, agents: {", ".join(agents)})', file=sys.stderr)
    print(f'[gen] problems: {pj}', file=sys.stderr)
    print(out)  # stdout = the path, for scripting


if __name__ == '__main__':
    main()
