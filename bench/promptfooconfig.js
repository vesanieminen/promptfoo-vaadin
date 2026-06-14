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
// The local plugin that bundles the `playwright-cli` skill, for the Playwright CLI
// rows (`playwright: 'cli'`). It lives in THIS repo (next to the config) rather than
// the agentic-dx checkout: it's a promptfoo-bench artifact, and committing it keeps
// the CLI rows reproducible (a pinned skill copy) and independent of AGENTIC_DX_DIR.
// See bench/playwright-cli-plugin/README.md.
const PLAYWRIGHT_CLI_PLUGIN = path.join(__dirname, 'playwright-cli-plugin');

// How a setup drives a browser (bench.SETUPS `playwright`): 'mcp' wires the Playwright
// MCP server below; 'cli' wires NO Playwright MCP and instead loads the playwright-cli
// skill so the agent drives the browser via the `playwright-cli` command (Bash).
const usesPlaywrightCli = (key) => key === 'cli';

// Benchmark integrity: `playwright-cli` is globally installed (on PATH), so an MCP row
// will `which playwright-cli` and drive the browser with the CLI instead of the
// Playwright MCP it's meant to measure — observed 2026-06-12: the MCP `claude` row made
// 17 CLI / 0 mcp__playwright calls on 2 of 3 problems, collapsing the A/B. The fix is the
// disallowed_tools deny below (DENY_PLAYWRIGHT_CLI), applied to the MCP rows only.
const DENY_PLAYWRIGHT_CLI = ['Bash(playwright-cli:*)', 'Bash(playwright-cli)'];

// Playwright (chromium) as an in-memory (`--isolated`) browser, so the concurrent
// solver rows don't deadlock on a shared profile lock. Registered per provider — but
// ONLY for `playwright: 'mcp'` rows (the 'cli' rows use the playwright-cli command).
const playwrightArgs = ['--yes', '@playwright/mcp@latest', '--browser', 'chromium', '--headless', '--isolated'];
// The Vaadin docs MCP the agent-skills plugin bundles. REMOTE is the hosted server
// (used by codex + the `claude` row); LOCAL is the server under test in the
// `claude-local-mcp` A/B (a local HTTP MCP on :18080, /docs endpoint).
const VAADIN_MCP_REMOTE = 'https://mcp.vaadin.com/docs';
const VAADIN_MCP_LOCAL = 'http://localhost:18080/docs';

// Map a setup's symbolic `vaadinMcp` ('remote' | 'local' | null) to the actual URL. The
// symbolic key lives in bench.SETUPS (so the matrix stays free of URLs); the URL binding
// lives here, next to the constants.
function resolveVaadinMcp(key) {
  if (key === 'remote') return VAADIN_MCP_REMOTE;
  if (key === 'local') return VAADIN_MCP_LOCAL;
  return null; // no Vaadin docs MCP — the no-help baseline
}

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
  '  - Chromium is already installed; use whichever Playwright tooling is available to you.',
  '  - Prefer accessibility snapshots / DOM queries for behavior verification; reserve screenshots for layout/visual rubric items.',
  '',
  "The app's HTTP port is set in `app/src/main/resources/application.properties`",
  '(`server.port`); use that port (not necessarily 8080) when previewing in a browser.',
].join('\n');

// Build the provider for a `claude` setup (id `anthropic:claude-code`). The Claude
// conditions differ ONLY in the docs help they get; everything else (pinned model,
// bypass perms, clean setting_sources, Playwright) is identical, so the rubric/trace
// delta isolates the docs-help variable:
//   - skills     → load the agent-skills plugin (layouts, responsive-layouts, …)
//   - vaadinMcp  → wire that Vaadin docs MCP ('remote'/'local'/null; null = the baseline)
//   - playwright → 'mcp' wires the Playwright MCP; 'cli' wires NO Playwright MCP and
//                  loads the playwright-cli skill plugin so the agent drives the
//                  browser via the `playwright-cli` command instead.
// `label` is also the workspace name (wd(label) → workspaces/<problem>/<label>); it
// comes straight from bench.SETUPS, so seed.js has already seeded a workspace for it.
function claudeSolver({ label, skills, vaadinMcp, playwright }) {
  const cli = usesPlaywrightCli(playwright);
  // The Playwright MCP is wired only for the 'mcp' rows; the 'cli' rows get the skill
  // (below) and drive the browser through Bash(`playwright-cli ...`) — no MCP server.
  const servers = cli ? [] : [{ name: 'playwright', command: 'npx', args: playwrightArgs }];
  const vaadinMcpUrl = resolveVaadinMcp(vaadinMcp);
  // The Vaadin docs MCP must be wired EXPLICITLY: the claude-agent-sdk provider loads
  // the plugin's SKILLS (via plugins:) but NOT its bundled .mcp.json, so without this
  // entry the agent makes zero mcp__vaadin calls even with the plugin (probe-verified).
  if (vaadinMcpUrl) servers.push({ name: 'vaadin', url: vaadinMcpUrl });
  const config = {
    apiKeyRequired: false, // fall back to subscription (CLAUDE_CODE_OAUTH_TOKEN / login) when ANTHROPIC_API_KEY is unset
    model: 'claude-opus-4-8', // PINNED for reproducibility — only the docs-help differs across rows
    effort: 'medium', // PINNED — matches codex's model_reasoning_effort so the two agents are compared at the same effort rung (else claude-code defaults to xhigh vs codex's medium)
    working_dir: wd(label),
    permission_mode: 'bypassPermissions',
    allow_dangerously_skip_permissions: true,
    allow_all_tools: true,
    setting_sources: [], // ignore the user's personal settings/plugins → clean benchmark
    mcp: { servers },
  };
  // Stop the MCP rows from reaching for the globally-installed `playwright-cli` (which
  // would bypass the Playwright MCP they're measuring). The provider forwards
  // config.disallowed_tools → SDK disallowedTools, enforced even under bypassPermissions;
  // it removes the matching Bash invocations from the model's context, and Claude Code
  // decomposes compound commands so `cd … && playwright-cli …` is denied too
  // (probe-verified 2026-06-12). The CLI rows are NOT denied — their browser path IS the
  // CLI. Note: this matches command strings, so a deliberate `npx playwright-cli` or
  // `bash -c '…'` would slip through — a theoretical gap the agent hasn't exercised.
  if (!cli) config.disallowed_tools = DENY_PLAYWRIGHT_CLI;
  // Plugins, as ABSOLUTE paths so they resolve from any config location (worktree
  // included): the Vaadin agent-skills plugin (from AGENTIC_DX_DIR) when `skills`, and
  // the bundled playwright-cli skill plugin when this is a Playwright CLI row. With
  // setting_sources:[] the agent ignores ~/.claude, so the CLI skill MUST come via a
  // plugin here — exactly like the agent-skills wiring.
  const plugins = [];
  if (skills) plugins.push({ type: 'local', path: AGENT_SKILLS_PLUGIN });
  if (cli) plugins.push({ type: 'local', path: PLAYWRIGHT_CLI_PLUGIN });
  if (plugins.length) config.plugins = plugins;
  return { id: 'anthropic:claude-code', label, config }; // = anthropic:claude-agent-sdk
}

// Build the provider for a `codex` setup (id `openai:codex:<model>`). Codex has no
// first-class plugin/mcp key, so its config goes via cli_config; its skills are seeded
// into the workspace's `.agents/skills/` by seed.js (not declared here), so `skills` is
// informational for codex. The Vaadin docs MCP is resolved the same way as Claude's.
// `playwright`: 'mcp' wires the Playwright MCP; 'cli' wires none and relies on the
// playwright-cli skill that seed.js seeds into `.agents/skills/playwright-cli`.
function codexSolver({ label, vaadinMcp, playwright }) {
  const mcp_servers = usesPlaywrightCli(playwright)
    ? {}
    : { playwright: { command: 'npx', args: playwrightArgs } };
  const vaadinMcpUrl = resolveVaadinMcp(vaadinMcp);
  if (vaadinMcpUrl) mcp_servers.vaadin = { url: vaadinMcpUrl }; // parity with the Claude rows
  return {
    id: 'openai:codex:gpt-5.5', // model lives in the id, like the root config
    label,
    config: {
      working_dir: wd(label),
      sandbox_mode: 'danger-full-access', // solving = write files, run mvn, start a server
      skip_git_repo_check: true,
      model_reasoning_effort: 'medium', // PINNED — parity with the claude rows' effort (codex's own default is also medium, but pin it so the matrix is explicit)
      cli_config: { mcp_servers }, // Codex has no first-class mcp/plugin key; config goes here
    },
  };
}

// Dispatch a bench.SETUPS entry to its agent's provider factory. Adding a new agent
// type is a one-line addition here; adding a new setup of an existing type needs no
// change at all (just the SETUPS entry in bench.js).
const SOLVER_FACTORY = { claude: claudeSolver, codex: codexSolver };
function solverProvider(setup) {
  const make = SOLVER_FACTORY[setup.agent];
  if (!make) throw new Error(`[bench] no provider factory for agent '${setup.agent}' (setup '${setup.label}')`);
  return make(setup);
}

module.exports = {
  // yaml-language-server style schema hint isn't needed for JS; promptfoo validates regardless.
  description: `agentic-dx ${PROBLEM} — Codex vs Claude solve the Vaadin task, both graded by the rubric verifier`,

  // beforeAll hook: (re)creates one fresh workspace per solver under
  // workspaces/<problem>/<agent>, seeds skeleton + task files, strips rubric.md
  // (seed_verify.js restores it for phase 2), bakes the per-(problem,agent) port,
  // and writes the availability manifest. Source override: AGENTIC_DX_DIR.
  extensions: ['file://seed.js:seed'],

  prompts: [PROMPT],

  // The SOLVERS, as promptfoo's native agentic providers — one per bench.SETUPS entry,
  // built by that setup's agent factory (codex's skills are seeded by seed.js into
  // .agents/skills; Claude's are loaded via the plugin). Each runs in its OWN
  // working_dir (seeded above) on its OWN baked port, so the rows are safe to run
  // together with --max-concurrency 3. Models are PINNED for reproducibility
  // (claude-opus-4-8; codex gpt-5.5 in the id), NOT perf-tuned. Both authenticate
  // via a subscription unless run.sh sets an API key. To add/remove a solver, edit
  // bench.SETUPS — this list follows automatically.
  providers: bench.SETUPS.map(solverProvider),

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
