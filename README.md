# Promptfoo eval starter

A minimal, runnable [promptfoo](https://www.promptfoo.dev/docs/intro/) setup that
evaluates a support-ticket triage prompt.

## Prerequisites

- Node.js 18+
- An API key for whichever provider you enable in `promptfooconfig.yaml`:
  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...
  # export OPENAI_API_KEY=sk-...
  ```

## Run it

```bash
# Run the eval (prompts × providers × tests)
npx promptfoo@latest eval

# Open the results in the web viewer
npx promptfoo@latest view
```

`eval` prints a pass/fail table and exits non-zero if any assertion fails — so
you can drop the same command into CI to gate prompt changes.

## Make it yours

- **Change the prompt** → edit the `prompts:` block. Add a second prompt to A/B them.
- **Compare models** → uncomment extra lines under `providers:`.
- **Add test cases** → add entries under `tests:`, or swap the block for
  `tests: tests.csv` to load cases from `tests.csv` (column headers become vars;
  a `__expected` column can hold an inline assertion).
- **Score differently** → mix assertion types: `contains`, `equals`, `regex`,
  `is-json`, `cost`, `latency`, `similar` (embeddings), `llm-rubric`,
  `factuality`, or custom `javascript`/`python`.

Docs: https://www.promptfoo.dev/docs/configuration/guide/
