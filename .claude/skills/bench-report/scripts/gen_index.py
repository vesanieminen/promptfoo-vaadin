#!/usr/bin/env python3
"""
gen_index.py — build docs/bench-reports/index.html, a visual landing page that links
every bench run report in the folder.

It scans a directory for `bench-results-*.html` reports and, from each, extracts the run
date (filename), the <title>, the hero lede, and the solver legend chips — then renders a
card grid (newest first) in the same visual template the reports use. Re-run it whenever a
report is added or removed; it always reflects what's on disk.

Pure stdlib. Reuses CSS + palette helpers from gen_bench_report (same scripts/ dir).

Usage:
  python3 gen_index.py [--dir docs/bench-reports] [--out docs/bench-reports/index.html]
"""
import argparse, glob, html, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_bench_report import CSS_BASE, PALETTE, FALLBACK, cls_of  # noqa: E402

CHIP_RE = re.compile(r'<span class="chip c-([\w-]+)"><span class="dot d-[\w-]+"></span>([^<]*)</span>')
LEGEND_RE = re.compile(r'<div class="legend"[^>]*>(.*?)</div>', re.S)
LEDE_RE = re.compile(r'<p class="lede">(.*?)</p>', re.S)
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.S)
DATE_RE = re.compile(r'bench-results-(\d{4}-\d{2}-\d{2})')


def clean_text(s):
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)   # drop EDIT markers
    s = re.sub(r'<[^>]+>', '', s)                    # drop tags
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def extract(path):
    t = open(path, encoding='utf-8', errors='replace').read()
    fn = os.path.basename(path)
    date_m = DATE_RE.search(fn)
    date = date_m.group(1) if date_m else fn
    title_m = TITLE_RE.search(t)
    title = clean_text(title_m.group(1)) if title_m else fn
    lede_m = LEDE_RE.search(t)
    lede = clean_text(lede_m.group(1)) if lede_m else ''
    if len(lede) > 320:
        lede = lede[:317].rstrip() + '…'
    # legend chips: (canonical-class, display-label) — only from the hero legend block,
    # not the per-chart/table chips scattered through the report body.
    legend_m = LEGEND_RE.search(t)
    legend = legend_m.group(1) if legend_m else ''
    chips, seen = [], set()
    for cls, label in CHIP_RE.findall(legend):
        key = (cls, label.strip())
        if key not in seen:
            seen.add(key)
            chips.append((cls, html.unescape(label.strip())))
    return {'file': fn, 'date': date, 'title': title, 'lede': lede, 'chips': chips}


INDEX_CSS = """
  .lede2{font-size:19px;color:var(--muted);max-width:760px;margin:0}
  .reportgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:18px;margin-top:6px}
  .report{display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);padding:20px 22px;transition:transform .12s ease,box-shadow .12s ease}
  .report:hover{transform:translateY(-2px);box-shadow:0 2px 4px rgba(16,32,46,.08),0 14px 36px rgba(16,32,46,.12)}
  .report .rdate{font:800 13px/1 ui-monospace,monospace;color:var(--indigo);letter-spacing:.06em;text-transform:uppercase}
  .report .rtitle{font-size:20px;font-weight:800;letter-spacing:-.01em;margin:8px 0 2px}
  .report .ragents{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0 10px}
  .report .rlede{color:var(--muted);font-size:14px;line-height:1.55;flex:1}
  .report .rlinks{margin-top:16px;display:flex;gap:10px;align-items:center}
  .report a.btn{display:inline-flex;align-items:center;gap:6px;font:600 13.5px/1 -apple-system,system-ui,sans-serif;padding:9px 14px;border-radius:9px;background:var(--indigo);color:#fff}
  .report a.btn:hover{background:#4338ca;text-decoration:none}
  .report a.btn.ghost{background:#eef1fb;color:var(--indigo)} .report a.btn.ghost:hover{background:#e3e7fa}
  .about{margin-top:24px} .about ul{margin:6px 0;padding-left:20px} .about li{margin:7px 0;font-size:14.5px}
"""


def render(reports, assigned):
    e = html.escape
    # CSS for the union of all chip classes seen, mapped to palette colors
    seen_cls = []
    for r in reports:
        for cls, _ in r['chips']:
            if cls not in seen_cls:
                seen_cls.append(cls)
    chip_css = []
    for cls in seen_cls:
        col = PALETTE.get(cls)
        if not col:
            col = FALLBACK[len(assigned) % len(FALLBACK)]
            assigned[cls] = col
        chip_css.append(f'  .c-{cls}{{color:{col}}} .d-{cls}{{background:{col}}}')

    p = []
    p.append(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>agentic-DX bench — run reports</title>
<style>{CSS_BASE}
{chr(10).join(chip_css)}
{INDEX_CSS}</style></head><body>''')

    p.append(f'''<header class="hero"><div class="kicker">agentic-DX bench</div>
<h1>Run reports</h1>
<p class="lede2">One visual report per benchmark sweep — a promptfoo solve&rarr;verify pass over the
three Vaadin problems. Each links rubric scores, costs, per-problem deductions and the solvers'
result screenshots. Newest first; {len(reports)} report{"s" if len(reports)!=1 else ""} on file.</p>
</header><div class="wrap"><section style="border-top:0">''')

    p.append('<div class="reportgrid">')
    for r in reports:
        chips = ''.join(
            f'<span class="chip c-{cls}"><span class="dot d-{cls}"></span>{e(label)}</span>'
            for cls, label in r['chips']) or '<span class="mini">solver set not detected</span>'
        p.append(f'''<div class="report">
  <div class="rdate">{e(r["date"])}</div>
  <div class="rtitle">{e(r["title"])}</div>
  <div class="ragents">{chips}</div>
  <div class="rlede">{e(r["lede"]) or "&nbsp;"}</div>
  <div class="rlinks"><a class="btn" href="{e(r["file"])}">Open report →</a></div>
</div>''')
    p.append('</div>')

    p.append('''<div class="card pad about" style="margin-top:26px">
  <h3 style="margin-top:0">About these reports</h3>
  <ul>
    <li>Each report is one self-contained file — CSS and result screenshots are inlined, so it
        opens offline. Click any screenshot for a full-resolution lightbox.</li>
    <li>Agent colors are consistent throughout: <span class="c-codex">codex</span> = amber,
        <span class="c-claude">claude</span> = teal,
        <span class="c-claude-local-mcp">claude-local-mcp</span> = violet,
        <span class="c-claude-no-skills">claude-no-skills</span> = gray.</li>
    <li>Scores are <b>n = 1 per cell</b> — treat ±1–2 rubric points as noise. When no non-Claude
        solver runs, all grading is Claude-judging-Claude (self-grading); reports flag this.</li>
    <li>New reports are produced by the <code>bench-report</code> skill
        (<code>.claude/skills/bench-report/</code>); this page is regenerated by its
        <code>gen_index.py</code>. See <a href="README.md">README.md</a> for the text index and
        <code>bench/README.md</code> for how the bench itself works.</li>
  </ul>
</div>''')

    p.append('</section></div>')
    p.append('<footer>agentic-DX bench · run reports · regenerate with <code>gen_index.py</code></footer>')
    p.append('</body></html>')
    return '\n'.join(p)


def main():
    ap = argparse.ArgumentParser(description='Generate the bench-reports index landing page.')
    ap.add_argument('--dir', default='docs/bench-reports', help='folder of reports')
    ap.add_argument('--out', default=None, help='output path (default <dir>/index.html)')
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, 'bench-results-*.html')))
    if not files:
        sys.exit(f'[index] no bench-results-*.html found in {args.dir}')
    reports = [extract(f) for f in files]
    reports.sort(key=lambda r: r['date'], reverse=True)  # newest first

    out = args.out or os.path.join(args.dir, 'index.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(render(reports, {}))
    print(f'[index] wrote {out} linking {len(reports)} report(s): ' +
          ', '.join(r['date'] for r in reports), file=sys.stderr)
    print(out)


if __name__ == '__main__':
    main()
