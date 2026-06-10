// promptfooconfig.js — PHASE 1 (solve), PROBLEM-parameterized.
//
// promptfoo port of the agentic-dx-improvement benchmark. This config is the SOLVE
// phase for ONE problem, chosen by the PROBLEM env var (default basic_layout; one
// of bench.PROBLEMS). run.sh sets PROBLEM per problem and runs this once per
// problem, so all problems show up side-by-side in `promptfoo view`. The rubric is
// graded in PHASE 2 (verify.js), where the verifier is a first-class provider
// rather than a subprocess — see docs/ADR-verifier-as-provider.md.
//
// It's a .js (not .yaml) config so the per-problem working_dir / description are
// computed from PROBLEM at load time (promptfoo loads .js configs via importModule
// and reads process.env at that point). The shared problem/agent/port/workspace
// layout lives in bench.js, imported by both configs and both seed hooks.
//
// Unlike the bespoke shell harness, the SOLVERS are promptfoo's BUILT-IN agentic
// providers, so there is no solve.sh / wrapper scripts and no model env knobs. The
// only custom code is seed.js (seeds the workspaces) and grade_static.py (source
// gate + solver-trace columns).
//
// Run from the repo root via the wrapper (warms Maven, --no-cache, run-scoped auth):
//   bash bench/run.sh                 # all problems × all agents
//   PROBLEM=basic_form bash bench/run.sh
//   npx promptfoo@latest view
//
// Auth (run.sh handles this): both the SOLVER and the rubric VERIFIER need Claude
// auth. run.sh resolves ONE run-scoped credential and injects it into the bench
// process only (never your rc files) — your choice of ANTHROPIC_API_KEY (API-key
// billing) or CLAUDE_CODE_OAUTH_TOKEN (subscription). See run.sh / README.md.

const path = require('path');
const bench = require('./bench.js');

const PROBLEM = bench.currentProblem(); // env PROBLEM (default basic_layout); throws on a typo

// The agentic-dx-improvement checkout (source of the agent-skills plugin), resolved
// the SAME way seed.js does: AGENTIC_DX_DIR if set, else the sibling of the repo
// root. We build an ABSOLUTE plugin path from it so the `claude` row's skills load
// regardless of where this config sits (e.g. a git worktree, where a relative
// `../../` would miss) — and so relocating the checkout only needs AGENTIC_DX_DIR,
// not a config edit.
const AGENTIC_DX_DIR = process.env.AGENTIC_DX_DIR
  ? path.resolve(process.env.AGENTIC_DX_DIR)
  : path.resolve(__dirname, '..', '..', 'agentic-dx-improvement');
const AGENT_SKILLS_PLUGIN = path.join(AGENTIC_DX_DIR, 'agent-skills');

// Playwright (chromium) as an in-memory (`--isolated`) browser, so the concurrent
// solver rows don't deadlock on a shared profile lock. Registered per provider.
const playwrightArgs = ['--yes', '@playwright/mcp@latest', '--browser', 'chromium', '--headless', '--isolated'];
// The Vaadin docs MCP the agent-skills plugin bundles (used by codex + claude rows).
const VAADIN_MCP_URL = 'https://mcp.vaadin.com/docs';

// workspaces/<problem>/<agent>, resolved by promptfoo relative to THIS config's dir
// — the exact path seed.js seeds (both via bench.workspaceRel).
const wd = (agent) => bench.workspaceRel(PROBLEM, agent);

// The base prompt: base_prompt_vaadin.md plus the "task is in the cwd" preamble. The
// real instructions (task.md) and reference PNGs are seeded into each workspace by
// seed.js and read by the agent from its working_dir. All three problems use the
// Vaadin skeleton, so this prompt is shared. Keep in sync with:
//   ../agentic-dx-improvement/problems/base_prompt_vaadin.md
const PROMPT = [
  'The task description and any reference assets are in the current working directory.',
  '',
  '- Solve the task specified in `task.md`.',
  '- If there is a `README.md` file, check it as well.',
  '- Prefer Vaadin built-in styles to custom ones.',
  '- Use the locally installed JDK 25 and Maven.',
  '- Use `dev.sh` to run the application in development mode. The dev server has Spring Boot Dev Tools enabled.',
  '- Use `run.sh` to run the application in production mode. When running in production mode, the application must be restarted for any changes to show up (including CSS changes).',
  '- When asked to write UI tests, write browserless UI tests.',
  '- If something can be verified using both a browserless UI test and using Playwright, prefer the browserless UI test.',
  '- Use Playwright to look at the end result in a browser.',
  '  - It is already installed (chromium) and available as an MCP.',
  '  - Use browser_snapshot / DOM queries for behavior verification; reserve screenshots for layout/visual rubric items.',
  '',
  "The app's HTTP port is set in `app/src/main/resources/application.properties`",
  '(`server.port`); use that port (not necessarily 8080) when previewing in a browser.',
].join('\n');

module.exports = {
  // yaml-language-server style schema hint isn't needed for JS; promptfoo validates regardless.
  description: `agentic-dx ${PROBLEM} — Codex vs Claude solve the Vaadin task, both graded by the rubric verifier`,

  // beforeAll hook: (re)creates one fresh workspace per solver under
  // workspaces/<problem>/<agent>, seeds skeleton + task files, strips rubric.md
  // (seed_verify.js restores it for phase 2), bakes the per-(problem,agent) port,
  // and writes the availability manifest. Source override: AGENTIC_DX_DIR.
  extensions: ['file://seed.js:seed'],

  prompts: [PROMPT],

  // The SOLVERS, as promptfoo's native agentic providers. Each runs in its OWN
  // working_dir (seeded above) on its OWN baked port, so the rows are safe to run
  // together with --max-concurrency 3. Models are PINNED for reproducibility
  // (claude-opus-4-8; codex gpt-5.5 in the id), NOT perf-tuned. Both authenticate
  // via a subscription unless run.sh sets an API key.
  providers: [
    {
      id: 'openai:codex:gpt-5.5', // model lives in the id, like the root config
      label: 'codex',
      config: {
        working_dir: wd('codex'),
        sandbox_mode: 'danger-full-access', // solving = write files, run mvn, start a server
        skip_git_repo_check: true,
        // Codex has no plugin loader; seed.js installs agent-skills' skills/ into this
        // workspace's `.agents/skills/` (Codex's discovery location) for parity with
        // the Claude row's plugin. promptfoo auto-detects their use → metadata.skillCalls.
        cli_config: {
          // Codex has no first-class mcp/plugin key; config goes via cli_config.
          mcp_servers: {
            playwright: { command: 'npx', args: playwrightArgs },
            vaadin: { url: VAADIN_MCP_URL }, // parity with Claude
          },
        },
      },
    },
    {
      id: 'anthropic:claude-code', // = anthropic:claude-agent-sdk (the agentic Claude Code provider)
      label: 'claude',
      config: {
        apiKeyRequired: false, // fall back to subscription (CLAUDE_CODE_OAUTH_TOKEN / login) when ANTHROPIC_API_KEY is unset
        model: 'claude-opus-4-8', // PINNED for reproducibility
        working_dir: wd('claude'),
        permission_mode: 'bypassPermissions',
        allow_dangerously_skip_permissions: true,
        allow_all_tools: true,
        setting_sources: [], // ignore the user's personal settings/plugins → clean benchmark
        // The Vaadin agent-skills plugin (layouts, responsive-layouts, …), as an
        // ABSOLUTE path derived from AGENTIC_DX_DIR (see above) so it resolves from
        // any config location (worktree included).
        plugins: [{ type: 'local', path: AGENT_SKILLS_PLUGIN }],
        mcp: {
          servers: [
            { name: 'playwright', command: 'npx', args: playwrightArgs },
            // Vaadin docs MCP, declared EXPLICITLY: the claude-agent-sdk provider loads
            // the plugin's SKILLS (via plugins:) but NOT its bundled .mcp.json, so the
            // server must be wired here (mirrors the codex row's cli_config). Verified by
            // a with-skills probe — without this, zero mcp__vaadin calls.
            { name: 'vaadin', url: VAADIN_MCP_URL },
          ],
        },
      },
    },
    {
      id: 'anthropic:claude-code', // BASELINE — same solver as `claude`, MINUS the Vaadin skills AND the docs MCP
      label: 'claude-no-skills',
      config: {
        apiKeyRequired: false,
        model: 'claude-opus-4-8', // same pin as `claude` so the ONLY difference is the skills
        working_dir: wd('claude-no-skills'),
        permission_mode: 'bypassPermissions',
        allow_dangerously_skip_permissions: true,
        allow_all_tools: true,
        setting_sources: [],
        // NO plugins (no Vaadin agent-skills) and NO Vaadin docs MCP — this row isolates
        // how much the skills move the rubric (the benchmark's thesis). Playwright stays
        // so it can self-verify in a browser like the others.
        mcp: {
          servers: [{ name: 'playwright', command: 'npx', args: playwrightArgs }],
        },
      },
    },
  ],

  // A single agentic task (no per-case vars). grade_static.py is the cheap,
  // deterministic source gate (the rubric's source-verifiable bullets, dispatched
  // per PROBLEM) AND emits the SOLVER's behavioural-trace diagnostic columns
  // (skill_calls, mcp_calls, num_turns, solve_seconds, cache_read_ktokens, …). Per
  // ADR 0002 the trace is the real DX signal; it's diagnostic, not pass/fail. The
  // rubric verdict is graded in PHASE 2 (verify.js).
  tests: [
    {
      description: `${PROBLEM} solved from the Vaadin skeleton (source gate + solver trace; rubric graded in phase 2)`,
      assert: [{ type: 'python', value: 'file://grade_static.py' }],
    },
  ],
};
