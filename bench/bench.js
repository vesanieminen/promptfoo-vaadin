// bench.js — single source of truth for the multi-problem agentic-dx benchmark.
//
// Imported by BOTH the promptfoo configs (promptfooconfig.js, verify.js) and the
// seed hooks (seed.js, seed_verify.js) so the problem list, the solver/agent list,
// the per-(problem,agent) port assignment, and the workspace path layout are
// defined in exactly ONE place. Keep the Python graders (grade_static.py,
// grade_verdict.py) in sync with PROBLEMS / SOLVERS / the workspace layout — they
// re-derive the same paths from PROBLEM (env) + the provider label.
//
// Adding a 4th problem is a drop-in: append its name to PROBLEMS, drop a
// problems/<name>/ (task.md + rubric.md [+ PNGs]) into the agentic-dx-improvement
// checkout, and add checks/<name>.py. Ports and workspace dirs follow automatically.

const path = require('path');

// Canonical problem order. Port offsets derive from a problem's INDEX here, so the
// order is load-bearing: appending keeps existing problems' ports stable.
const PROBLEMS = ['basic_layout', 'basic_form', 'md_ui_spec'];

// Solver setups — the single source of truth for the solver matrix. Each entry is one
// benchmark "setup": a `label` (which is BOTH the workspace name and the port key), the
// `agent` that runs it, and the docs-help it gets. ORDER IS LOAD-BEARING — a setup's
// port offset derives from its index here (via SOLVERS below), so appending a setup
// keeps existing setups' ports stable. Adding a setup is a ONE-LINE edit HERE:
// promptfooconfig.js builds a provider for each entry (dispatching on `agent`), SOLVERS
// derives from it, and verify.js maps SOLVERS to verifiers — none of which need
// touching. The skills A/B is `claude` vs `claude-no-skills`; the local-MCP A/B is
// `claude` vs `claude-local-mcp`; the Playwright MCP-vs-CLI A/B is `claude` vs
// `claude-pw-cli` (and `codex` vs `codex-pw-cli`); `codex` is the cross-agent comparison.
//   - agent      'claude' | 'codex' — which provider factory builds the row
//   - skills     load the agent-skills plugin (claude) / seed skills into .agents/skills (codex)
//   - vaadinMcp  which Vaadin docs MCP to wire: 'remote' (hosted), 'local' (under test), or null (none)
//   - playwright how the agent drives a browser: 'mcp' (the Playwright MCP server, default) or
//                'cli' (the `playwright-cli` command + its skill — no Playwright MCP wired). The
//                Playwright MCP README recommends CLI+SKILLS over MCP for token efficiency; the
//                `*-pw-cli` rows measure that trade-off (see bench/playwright-cli-plugin/README.md).
const SETUPS = [
  { label: 'codex',            agent: 'codex',  skills: true,  vaadinMcp: 'remote', playwright: 'mcp' },
  { label: 'claude',           agent: 'claude', skills: true,  vaadinMcp: 'remote', playwright: 'mcp' },
  { label: 'claude-no-skills', agent: 'claude', skills: false, vaadinMcp: null,     playwright: 'mcp' },
  { label: 'claude-local-mcp', agent: 'claude', skills: true,  vaadinMcp: 'local',  playwright: 'mcp' },
  { label: 'claude-pw-cli',    agent: 'claude', skills: true,  vaadinMcp: 'remote', playwright: 'cli' },
  { label: 'codex-pw-cli',     agent: 'codex',  skills: true,  vaadinMcp: 'remote', playwright: 'cli' },
];

// Solver labels (= workspace names), in port order within a problem. Derived from
// SETUPS so the matrix and the label list can never drift. The Python graders
// (grade_static.py / grade_verdict.py, `_WORKSPACES`) and run.sh (`_known`) keep their
// own copies of these labels — keep those in sync with the SETUPS labels above.
const SOLVERS = SETUPS.map((s) => s.label);

// First port (basic_layout/codex). Each problem reserves SOLVERS.length consecutive
// ports, so the three problems (× SOLVERS.length setups each) occupy a contiguous
// block starting here and never collide — even if two problems' rows were somehow
// run concurrently. (Adding setups widens each problem's block; ports are recomputed
// from SETUPS every seed, so nothing hardcodes the old range.)
const PORT_BASE = 8081;

function problemIndex(problem) {
  const i = PROBLEMS.indexOf(problem);
  if (i < 0) throw new Error(`[bench] unknown PROBLEM '${problem}' (known: ${PROBLEMS.join(', ')})`);
  return i;
}

// Deterministic, collision-free port for a (problem, agent) pair.
function portFor(problem, agent) {
  const a = SOLVERS.indexOf(agent);
  if (a < 0) throw new Error(`[bench] unknown agent '${agent}' (known: ${SOLVERS.join(', ')})`);
  return PORT_BASE + problemIndex(problem) * SOLVERS.length + a;
}

// workspaces/<problem>/<agent>, RELATIVE to the bench dir. Used verbatim as a
// promptfoo provider `working_dir` (promptfoo resolves it against the config dir)
// and joined under __dirname in the seed hooks.
function workspaceRel(problem, agent) {
  return path.posix.join('workspaces', problem, agent);
}

// The problem this invocation is for. run.sh sets PROBLEM per problem; default
// keeps a bare `eval -c promptfooconfig.js` working as the original basic_layout run.
function currentProblem() {
  const p = process.env.PROBLEM || 'basic_layout';
  problemIndex(p); // validate (throws on typo) before the config is handed to promptfoo
  return p;
}

module.exports = {
  PROBLEMS,
  SETUPS,
  SOLVERS,
  PORT_BASE,
  problemIndex,
  portFor,
  workspaceRel,
  currentProblem,
};
