#!/usr/bin/env python3
"""
Extract one agentic-dx bench run into data + screenshots — nothing else.

A "run" is a solve->verify sweep over the three problems, which lands as a
contiguous range of promptfoo evals on localhost:15500. Given the range's start
and end eval (URL or id), this pulls the numbers a report needs and writes the
attached result screenshots to files. It deliberately does NOT write HTML or any
narrative/caveat prose: the framing (self- vs cross-grading, hang-vs-failure,
which shots matter) is a judgement call best made by prompting over this output,
not templated. See docs/bench-reports/README.md.

Outputs (to --out-dir, default bench/extracts/<end-id>/):
  - run.json   — full structured data (machine-readable)
  - run.md     — a flat markdown summary (tables + per-bullet deductions + flags)
  - *.png      — every screenshot attached to the solve rows
and prints run.md to stdout.

Loud failure modes (so a shape change can't ship as a clean-but-wrong report):
  - exits 2 if the rubric extraction yields all-zero maxes (output shape changed),
  - flags any verify row whose structured output could not be parsed,
  - flags hung solve rows (timeout / exit 143) and configured-but-absent solvers.

Pure stdlib. Blobs are read from <config-dir>/blobs (default ~/.promptfoo).
"""
import argparse, json, os, re, sys, urllib.request

PREF_ORDER = ['codex', 'claude', 'claude-local-mcp', 'claude-no-skills']
PROBLEM_ORDER = ['basic_layout', 'basic_form', 'md_ui_spec']
PHASE_RE = re.compile(r'agentic-dx\s+([a-z0-9_]+)\s+[—-]', re.I)


# ---- helpers ---------------------------------------------------------------

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
    """Width x height from a PNG header, no image library."""
    if len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    return 0, 0


def load_blob(config_dir, h):
    f = os.path.join(config_dir, 'blobs', h[:2], h[2:4], h)
    return open(f, 'rb').read() if os.path.exists(f) else None


def order_agents(agents):
    known = [a for a in PREF_ORDER if a in agents]
    return known + sorted(a for a in agents if a not in PREF_ORDER)


def verifier_name(provider_id):
    """openai:codex:... -> codex ; anthropic:claude-* -> claude ; else the id."""
    pid = (provider_id or '').lower()
    if 'codex' in pid or pid.startswith('openai:'):
        return 'codex'
    if 'claude' in pid or 'anthropic' in pid:
        return 'claude'
    return provider_id or 'unknown'


# ---- selection + parsing ---------------------------------------------------

def select_evals(base_url, start_id, end_id):
    data = fetch_json(f'{base_url}/api/results')['data']
    by_id = {e['evalId']: e for e in data}
    missing = [x for x in (start_id, end_id) if x not in by_id]
    if missing:
        sys.exit(f'[extract] eval id(s) not found on server: {", ".join(missing)}')
    lo = min(by_id[start_id]['createdAt'], by_id[end_id]['createdAt'])
    hi = max(by_id[start_id]['createdAt'], by_id[end_id]['createdAt'])
    chosen = [e for e in data if lo <= e['createdAt'] <= hi]
    chosen.sort(key=lambda e: e['createdAt'])
    return chosen


def classify(desc):
    m = PHASE_RE.search(desc or '')
    if not m:
        return None, None
    phase = 'verify' if ('PHASE 2' in (desc or '') or 'grade each solved' in (desc or '')) else 'solve'
    return m.group(1), phase


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
    err = row.get('error') or resp.get('error')   # timeout lives at row level
    success = bool(row.get('success'))
    hung = (not success) and bool(err)
    latency_ms = row.get('latencyMs') or resp.get('latencyMs')
    imgs = [im.get('blobRef', {}).get('hash') for im in (resp.get('images') or [])
            if im.get('blobRef', {}).get('hash')]
    return {
        'success': success, 'hung': hung, 'error': (str(err)[:200] if err else None),
        'static_score': row.get('score'), 'cost': row.get('cost') or 0.0,
        'latency_ms': latency_ms, 'static_detail': static_detail, 'fails': fails,
        'img_hashes': imgs,
        'ns': {k: ns.get(k) for k in ('skill_calls', 'mcp_calls', 'tool_calls', 'tool_errors',
                                      'api_archaeology_calls', 'num_turns', 'solve_seconds',
                                      'cache_read_ktokens', 'output_tokens')},
    }


def parse_verify(row):
    out = (row.get('response') or {}).get('output')
    # Some verifier providers (e.g. codex) return the structured verdict as a JSON
    # string rather than an already-parsed dict (as the claude provider does).
    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            out = None
    sections, deductions, tot, mx = [], [], 0, 0
    parsed = isinstance(out, dict) and bool(out.get('criteria'))
    if isinstance(out, dict):
        for s in (out.get('criteria') or []):
            sc, m = s.get('score', 0), s.get('max-score', 0)
            tot += sc; mx += m
            sections.append({'section': s.get('section'), 'score': sc, 'max': m})
            for b in s.get('bullets', []):
                if b.get('score', 1) < 1:
                    deductions.append({'section': s.get('section'), 'name': b.get('name'),
                                       'feedback': (b.get('feedback') or '').strip()})
    return {'success': bool(row.get('success')), 'parsed': parsed,
            'norm': row.get('score') or 0.0, 'cost': row.get('cost') or 0.0,
            'raw': tot, 'max': mx, 'sections': sections, 'deductions': deductions}


def configured_labels(detail):
    out = []
    for p in (detail.get('config', {}) or {}).get('providers', []) or []:
        lab = p.get('label') if isinstance(p, dict) else p
        if lab:
            out.append(lab.replace('verify-', ''))
    return out


def build_model(base_url, chosen):
    problems, skipped, verifier_ids = {}, [], set()
    for e in chosen:
        prob, phase = classify(e.get('description', ''))
        if not prob:
            skipped.append(e['evalId'])
            continue
        detail = fetch_json(f"{base_url}/api/results/{e['evalId']}")['data']
        rows = detail['results']['results']
        p = problems.setdefault(prob, {'solve_eval': None, 'verify_eval': None,
                                       'solve': {}, 'verify': {},
                                       'configured_solvers': [], 'configured_verifiers': []})
        p[f'{phase}_eval'] = e['evalId']
        p['configured_solvers' if phase == 'solve' else 'configured_verifiers'] = configured_labels(detail)
        for row in rows:
            prov = row.get('provider') or {}
            agent = (prov.get('label') or '?')
            if phase == 'verify':
                verifier_ids.add(prov.get('id'))
                p['verify'][agent.replace('verify-', '')] = parse_verify(row)
            else:
                p['solve'][agent] = parse_solve(row)
    return problems, skipped, verifier_ids


# ---- screenshots -----------------------------------------------------------

def write_screenshots(problems, config_dir, out_dir, enabled):
    manifest = []
    if not enabled:
        return manifest
    for prob in [p for p in PROBLEM_ORDER if p in problems] + \
                [p for p in problems if p not in PROBLEM_ORDER]:
        for agent in order_agents(problems[prob]['solve']):
            for i, h in enumerate(problems[prob]['solve'][agent]['img_hashes']):
                data = load_blob(config_dir, h)
                if not data:
                    manifest.append({'problem': prob, 'agent': agent, 'hash': h,
                                     'file': None, 'note': 'blob missing on disk'})
                    continue
                w, hh = png_dims(data)
                fn = f'{prob}__{agent}__{w}x{hh}__{i}.png'
                with open(os.path.join(out_dir, fn), 'wb') as f:
                    f.write(data)
                manifest.append({'problem': prob, 'agent': agent, 'dims': f'{w}x{hh}',
                                 'file': fn, 'hash': h})
    return manifest


# ---- markdown rendering ----------------------------------------------------

def money(x):
    return f'${x:,.2f}'


def wall(solve):
    s = solve['ns'].get('solve_seconds')
    if not s and solve.get('latency_ms'):
        s = solve['latency_ms'] / 1000.0
    if not s:
        return '—'
    return f'{s/60:.1f}m' if s >= 600 else f'{int(s)}s'


def render_md(meta, problems, manifest, flags):
    L = []
    L.append(f'# bench run extract — `{meta["start"]}` → `{meta["end"]}`\n')
    L.append(f'- Server: `{meta["base_url"]}`')
    L.append(f'- **Verifier: {meta["verifier"]}** (`{meta["verifier_id"]}`) — '
             f'{"cross-grading (verifier ≠ a Claude solver)" if meta["verifier"]=="codex" else "self-grading if solvers are Claude"}')
    L.append(f'- Solvers present: {", ".join(meta["solvers_present"]) or "(none)"}')
    if meta['solvers_absent']:
        L.append(f'- ⚠ Configured but ABSENT (0 rows): {", ".join(meta["solvers_absent"])}')
    L.append(f'- Screenshots written: {sum(1 for m in manifest if m.get("file"))} '
             f'(of {len(manifest)} attached) → `{meta["out_dir"]}`\n')

    P = [p for p in PROBLEM_ORDER if p in problems] + [p for p in problems if p not in PROBLEM_ORDER]
    agents = order_agents({a for p in problems.values() for a in p['verify']} |
                          {a for p in problems.values() for a in p['solve']})

    # Rubric table
    L.append(f'## Rubric scores (phase 2, {meta["verifier"]}-graded)\n')
    L.append('| problem | max | ' + ' | '.join(agents) + ' |')
    L.append('|' + '---|' * (len(agents) + 2))
    for prob in P:
        v = problems[prob]['verify']
        mx = max((d['max'] for d in v.values()), default=0)
        cells = []
        for a in agents:
            d = v.get(a)
            cells.append(f'{d["raw"]}/{d["max"]} ({round(100*d["raw"]/d["max"]) if d["max"] else 0}%)'
                         if d else '—')
        L.append(f'| {prob} | {mx} | ' + ' | '.join(cells) + ' |')
    L.append('')

    # Cost summary
    L.append('## Cost (USD)\n')
    L.append('| agent | solve | verify | total |')
    L.append('|---|---|---|---|')
    gtotal = 0.0
    for a in agents:
        sc = sum(problems[p]['solve'].get(a, {}).get('cost', 0) for p in P)
        vc = sum(problems[p]['verify'].get(a, {}).get('cost', 0) for p in P)
        gtotal += sc + vc
        L.append(f'| {a} | {money(sc)} | {money(vc)} | {money(sc+vc)} |')
    L.append(f'\n**Sweep total: {money(gtotal)}**'
             + ('  ⚠ understated — hung solve rows recorded $0' if flags['hung'] else ''))
    L.append('')

    # Per-problem detail
    for prob in P:
        L.append(f'## {prob}\n')
        s = problems[prob]['solve']
        L.append('### solve')
        L.append('| agent | ok | hung | static | cost | wall | turns | mcp | tool(err) | shots |')
        L.append('|---|---|---|---|---|---|---|---|---|---|')
        for a in order_agents(s):
            d = s[a]
            ns = d['ns']
            stat = d['static_score']
            stat = round(stat, 3) if isinstance(stat, (int, float)) else stat
            L.append(f'| {a} | {"✓" if d["success"] else "✗"} | {"HUNG" if d["hung"] else ""} '
                     f'| {stat} | {money(d["cost"])} | {wall(d)} '
                     f'| {ns.get("num_turns") or "—"} | {ns.get("mcp_calls") or "—"} '
                     f'| {ns.get("tool_calls") or "—"} ({ns.get("tool_errors") or 0}) '
                     f'| {len(d["img_hashes"])} |')
        L.append('')
        L.append(f'### deductions ({meta["verifier"]}-graded)')
        v = problems[prob]['verify']
        any_ded = False
        for a in order_agents(v):
            d = v[a]
            head = f'- **{a}** ({d["raw"]}/{d["max"]})'
            if not d['parsed']:
                L.append(head + ' — ⚠ structured output could not be parsed')
                any_ded = True
                continue
            if not d['deductions']:
                L.append(head + ' — clean, no deductions')
                continue
            any_ded = True
            L.append(head + ':')
            for x in d['deductions']:
                L.append(f'  - *{x["section"]}* — {x["name"]}: {x["feedback"]}')
        if not any_ded:
            L.append('- (all clean)')
        L.append('')

    # Screenshot manifest
    L.append('## Screenshots\n')
    if manifest:
        for m in manifest:
            if m.get('file'):
                L.append(f'- `{m["file"]}` — {m["problem"]} / {m["agent"]} / {m.get("dims","?")}')
            else:
                L.append(f'- ⚠ {m["problem"]} / {m["agent"]} — {m.get("note","missing")}')
    else:
        L.append('- (none attached)')
    L.append('')

    # Flags
    L.append('## FLAGS')
    if flags['hung']:
        L.append('- HUNG solve rows (agent-SDK timeout/exit-143; workspace usually still built & graded): '
                 + '; '.join(flags['hung']))
    if meta['solvers_absent']:
        L.append('- ABSENT solvers (configured, 0 rows): ' + ', '.join(meta['solvers_absent']))
    if flags['unparsed']:
        L.append('- UNPARSED verify rows: ' + '; '.join(flags['unparsed']))
    if flags['skipped']:
        L.append('- Non-bench evals skipped in range: ' + ', '.join(flags['skipped']))
    if not (flags['hung'] or meta['solvers_absent'] or flags['unparsed'] or flags['skipped']):
        L.append('- none')
    L.append('')
    return '\n'.join(L)


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='Extract a bench run into data + screenshots (no HTML/prose).')
    ap.add_argument('--start', required=True, help='start eval URL or id')
    ap.add_argument('--end', required=True, help='end eval URL or id')
    ap.add_argument('--base-url', default='http://localhost:15500')
    ap.add_argument('--config-dir', default=os.path.expanduser('~/.promptfoo'),
                    help='promptfoo config dir holding blobs/ (default ~/.promptfoo)')
    ap.add_argument('--out-dir', default=None,
                    help='output dir (default bench/extracts/<end-id>/)')
    ap.add_argument('--no-screenshots', action='store_true')
    args = ap.parse_args()

    start_id, end_id = strip_id(args.start), strip_id(args.end)
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = args.out_dir or os.path.join(here, 'extracts', end_id.replace(':', '-'))
    os.makedirs(out_dir, exist_ok=True)

    chosen = select_evals(args.base_url, start_id, end_id)
    problems, skipped, verifier_ids = build_model(args.base_url, chosen)
    if not problems:
        sys.exit('[extract] no bench evals (agentic-dx ...) found in range')

    # Sanity: a verifier-shape change shows up as every rubric max == 0.
    total_max = sum(d['max'] for p in problems.values() for d in p['verify'].values())
    if total_max == 0 and any(p['verify'] for p in problems.values()):
        sys.exit('[extract] ERROR: all verify rubric maxes are 0 — the verifier output '
                 'shape likely changed; refusing to emit a clean-but-empty extract.')

    verifier_ids.discard(None)
    verifier_id = sorted(verifier_ids)[0] if verifier_ids else None
    if len(verifier_ids) > 1:
        print(f'[extract] WARNING: mixed verifier ids in range: {verifier_ids}', file=sys.stderr)

    solvers_present = order_agents({a for p in problems.values() for a in p['solve']})
    configured = set()
    for p in problems.values():
        configured.update(p['configured_solvers'])
    solvers_absent = [a for a in order_agents(configured) if a not in solvers_present]

    flags = {
        'hung': [f'{prob}/{a}' for prob in problems for a, d in problems[prob]['solve'].items() if d['hung']],
        'unparsed': [f'{prob}/{a}' for prob in problems for a, d in problems[prob]['verify'].items()
                     if not d['parsed']],
        'skipped': skipped,
    }
    manifest = write_screenshots(problems, args.config_dir, out_dir, not args.no_screenshots)

    meta = {'start': start_id, 'end': end_id, 'base_url': args.base_url, 'out_dir': out_dir,
            'verifier': verifier_name(verifier_id), 'verifier_id': verifier_id,
            'solvers_present': solvers_present, 'solvers_absent': solvers_absent}

    md = render_md(meta, problems, manifest, flags)
    with open(os.path.join(out_dir, 'run.json'), 'w') as f:
        json.dump({'meta': meta, 'flags': flags, 'screenshots': manifest, 'problems': problems},
                  f, indent=2)
    with open(os.path.join(out_dir, 'run.md'), 'w') as f:
        f.write(md)
    print(md)
    print(f'\n[extract] wrote run.json, run.md and {sum(1 for m in manifest if m.get("file"))} '
          f'screenshot(s) to {out_dir}', file=sys.stderr)


if __name__ == '__main__':
    main()
