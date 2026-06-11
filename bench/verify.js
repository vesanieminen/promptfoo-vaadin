// verify.js — PHASE 2 (verify), PROBLEM-parameterized.
//
// Phase 1 (promptfooconfig.js) runs the SOLVERS and leaves each agent's solution in
// workspaces/<problem>/<agent>/app. This phase grades those solutions for the SAME
// problem (PROBLEM env, default basic_layout). run.sh runs phase 1 then phase 2 for
// each problem in turn.
//
// THE KEY DESIGN CHANGE (see docs/ADR-verifier-as-provider.md): the rubric verifier
// is itself an agent — it runs the app, drives Playwright across viewports, and
// judges against rubric.md. So it is modelled as a first-class promptfoo PROVIDER,
// one per solved workspace — NOT a subprocess. This phase is problem-agnostic: the
// verifier reads whatever rubric.md seed_verify.js restored, and grade_verdict.py sums
// whatever sections the verdict reports and normalizes (so a 21/24, 23/31, or 41/48
// rubric all work with no code change).
//
// WHICH GRADER runs is selectable from the command line via the VERIFIER env var
// (default 'claude'): 'claude' → anthropic:claude-agent-sdk (model pinned
// claude-opus-4-8); 'codex' → openai:codex:gpt-5.5. The grader is GLOBAL for the run
// (same model grades every workspace), both read the SAME rubric and emit the SAME
// verdict schema, and the row labels stay `verify-<solver>` — so run.sh's AGENT filter
// and grade_verdict.py's provider->workspace mapping are unaffected by the choice.
//
// Run via the wrapper (does phase 1 then phase 2 for each problem):  bash bench/run.sh
//   VERIFIER=codex bash bench/run.sh        # grade with Codex instead of Claude
// Or directly (workspaces must already exist from a phase-1 run of the SAME problem):
//   PROBLEM=basic_form VERIFIER=codex npx promptfoo@latest eval -c bench/verify.js --max-concurrency 3 --no-cache

const bench = require('./bench.js');

const PROBLEM = bench.currentProblem(); // env PROBLEM (default basic_layout); throws on a typo

const playwrightArgs = ['--yes', '@playwright/mcp@latest', '--browser', 'chromium', '--headless', '--isolated'];

// The structured verdict schema, shared by all verifiers. Claude takes the full
// `output_format` wrapper; Codex (if/when wired for structured output) takes the bare
// JSON Schema in VERDICT_SCHEMA.schema.
const VERDICT_SCHEMA = {
  type: 'json_schema',
  schema: {
    type: 'object',
    required: ['criteria'],
    properties: {
      criteria: {
        type: 'array',
        items: {
          type: 'object',
          required: ['section', 'score', 'max-score'],
          properties: {
            section: { type: 'string' },
            score: { type: 'number' },
            'max-score': { type: 'number' },
            bullets: {
              type: 'array',
              items: {
                type: 'object',
                required: ['name', 'score'],
                properties: {
                  name: { type: 'string' },
                  score: { type: 'number' },
                  feedback: { type: 'string' },
                },
              },
            },
          },
        },
      },
    },
  },
};

// The grader, selectable from the command line via VERIFIER (default 'claude'). The
// chosen factory builds one provider per solved workspace, identical except
// working_dir. Each Playwright MCP is --isolated so the verifiers can run concurrently;
// each workspace's app is on its own baked port, so the apps don't collide either. The
// row label is `verify-<solver>` regardless of grader, so run.sh's AGENT filter and
// grade_verdict.py's provider->workspace mapping keep working.
const VERIFIER = (process.env.VERIFIER || 'claude').toLowerCase();

// Claude grader: first-class agentic provider, model PINNED (claude-opus-4-8) for
// reproducibility. apiKeyRequired:false lets it use ANTHROPIC_API_KEY when set or fall
// back to the Claude Code login. Structured output is enforced via output_format.
const claudeVerifier = (agent) => ({
  id: 'anthropic:claude-agent-sdk',
  label: `verify-${agent}`,
  config: {
    apiKeyRequired: false,
    model: 'claude-opus-4-8',
    working_dir: bench.workspaceRel(PROBLEM, agent), // workspaces/<problem>/<agent>
    permission_mode: 'bypassPermissions',
    allow_dangerously_skip_permissions: true,
    allow_all_tools: true,
    setting_sources: [],
    output_format: VERDICT_SCHEMA,
    mcp: { servers: [{ name: 'playwright', command: 'npx', args: playwrightArgs }] },
  },
});

// Codex grader: mirrors the phase-1 codex SOLVER's config surface (full-access sandbox
// so it can run app/run.sh + start a server, no git check, Playwright via cli_config).
// Model lives in the id, like the solver — keep `gpt-5.5` in sync with promptfooconfig.js.
// Codex authenticates via its OWN login (Codex Keychain / OPENAI_API_KEY), independent
// of the Anthropic credential run.sh manages — so VERIFIER=codex needs a Codex login.
// We deliberately do NOT set output_schema: OpenAI strict structured-output rejects our
// schema's optional fields, so Codex returns its verdict via the verify-result.json file
// the PROMPT mandates, which grade_verdict.py reads as its fallback. To enforce schema
// later, make VERDICT_SCHEMA.schema strict (additionalProperties:false + all-required)
// and add `output_schema: VERDICT_SCHEMA.schema` here.
const codexVerifier = (agent) => ({
  id: 'openai:codex:gpt-5.5',
  label: `verify-${agent}`,
  config: {
    working_dir: bench.workspaceRel(PROBLEM, agent), // workspaces/<problem>/<agent>
    sandbox_mode: 'danger-full-access',
    skip_git_repo_check: true,
    cli_config: { mcp_servers: { playwright: { command: 'npx', args: playwrightArgs } } },
  },
});

const VERIFIER_FACTORY = { claude: claudeVerifier, codex: codexVerifier };
const verifier = VERIFIER_FACTORY[VERIFIER];
if (!verifier) {
  throw new Error(`[bench] unknown VERIFIER '${VERIFIER}' (known: ${Object.keys(VERIFIER_FACTORY).join(', ')})`);
}

// The verifier instructions, port-agnostic: each workspace's app runs on its own
// baked server.port, so the verifier reads the port from application.properties
// instead of assuming 8080. Kept in sync with:
//   ../agentic-dx-improvement/problems/verify_prompt.md
const PROMPT = [
  'You are an expert code reviewer evaluating AI-generated code.',
  '',
  'The current working directory contains:',
  '- `prompt.txt` — the task prompt that was given to the AI agent.',
  '- `rubric.md` — the evaluation criteria and grading instructions.',
  "- `app/` — the agent's solution.",
  '',
  'Run the application by running the `app/run.sh` script. The app\'s HTTP port is',
  'set in `app/src/main/resources/application.properties` (`server.port`) — read it',
  'and wait for the application to start on THAT port (it is not necessarily 8080).',
  'Use that port throughout.',
  '',
  "Score the solution against the rubric, following the rubric's setup and grading",
  'instructions exactly.',
  '',
  'Playwright (chromium) is already installed and available as an MCP — use it to',
  'drive the browser when the rubric calls for it. Use browser_snapshot / DOM',
  'queries for behavior verification; reserve screenshots for layout/visual rubric',
  'items.',
  '',
  'Ignore any files ending in `.log` or `.log.jsonl` when scoring — they are',
  'transcripts from prior agent runs and are not part of the solution.',
  '',
  'Return your verdict as the configured STRUCTURED OUTPUT, and ALSO write the same',
  'JSON to a file named `verify-result.json` in the current working directory (for',
  'the record). Both must match this schema and contain nothing else:',
  '',
  '{',
  '  "criteria": [',
  '    { "section": "string", "score": 0, "max-score": 0,',
  '      "bullets": [ { "name": "string", "score": 0, "feedback": "string" } ] }',
  '  ]',
  '}',
].join('\n');

module.exports = {
  description: `agentic-dx ${PROBLEM} — PHASE 2: grade each solved workspace against the rubric (verifier: ${VERIFIER})`,

  // beforeAll hook: for each workspace, restore rubric.md (stripped during phase-1
  // seeding so the solver never saw it) and free the baked server port.
  extensions: ['file://seed_verify.js:seed'],

  prompts: [PROMPT],

  providers: bench.SOLVERS.map(verifier),

  // grade_verdict.py reads this row's structured verdict (fallback:
  // verify-result.json), normalizes to the rubric fraction, and passes if it clears
  // the floor (RUBRIC_PASS_THRESHOLD). Per-section fractions → rubric_<section> columns.
  tests: [
    {
      description: 'rubric verdict for the solved workspace',
      assert: [{ type: 'python', value: 'file://grade_verdict.py' }],
    },
  ],
};
