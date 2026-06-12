# playwright-cli-plugin

A tiny **local Claude plugin** that bundles the official `playwright-cli` skill so the
benchmark's Playwright **CLI** rows (`claude-pw-cli`, `codex-pw-cli`) can drive a
browser through the `playwright-cli` command instead of the Playwright **MCP**.

Why this exists: the solver providers run with `setting_sources: []` (a clean
benchmark that ignores your personal `~/.claude/skills` / plugins), so the
`playwright-cli` skill can't be picked up from your machine. The claude CLI rows
load it explicitly via `config.plugins` in `promptfooconfig.js`; the codex CLI row
gets the same skill seeded into its `.agents/skills/` by `seed.js`. Both read the
skill from THIS directory, so it's the single vendored source.

## What the choice is

The [Playwright MCP README](https://github.com/microsoft/playwright-mcp) recommends
**CLI + SKILLS** over MCP for coding agents on token-efficiency grounds (no large
tool schemas / verbose accessibility trees loaded into context). The benchmark now
measures that trade-off directly: the `*-pw-cli` rows are identical to their MCP
counterparts except the browser is driven via `playwright-cli` (Bash) rather than
`mcp__playwright__*` tools. The `playwright_cli_calls` grader column counts the CLI
invocations the way `mcp_calls` counts the MCP path.

## Provenance

Vendored from the globally-installed `@playwright/cli` package
(`/opt/homebrew/lib/node_modules/@playwright/cli/skills/playwright-cli`), version
**0.1.9**. Vendored (rather than symlinked to the global install) so the benchmark
is self-contained and reproducible — re-copy from a newer `@playwright/cli` to bump
it. The `playwright-cli` BINARY itself is NOT vendored; the rows rely on it being on
PATH (global `npm i -g @playwright/cli`), and the skill documents the
`npx --no-install playwright-cli` fallback.
