# Vaadin view code-generation eval (promptfoo)

A small, runnable [promptfoo](https://www.promptfoo.dev/docs/intro/) eval that tests
an agent's ability to generate a **Vaadin Flow (Java)** view from a short UI
description — modelled on the v25.2 starter (Spring Boot + Vaadin Flow; views extend
`VerticalLayout`, are annotated with `@Route`, and give components stable ids via
`setId(...)`).

This is the simple, one-shot sibling of [`basic_layout/`](basic_layout/README.md) —
the full *agentic* benchmark (the agents actually solve a task and are rubric-graded).
See that README for its (heavier) setup.

## What it runs

Prompts × providers × tests — one prompt, two providers, three views:

- **Prompt** → asks for a single compilable Vaadin Flow view (raw Java, no markdown).
- **Providers** → an A/B of two agents, **both on a subscription — no API key**:
  - `openai:codex:gpt-5.5` — promptfoo's built-in Codex provider; reuses your
    `codex login` state.
  - `anthropic:messages:claude-opus-4-8` — `apiKeyRequired: false` reuses your
    Claude Code login (`claude /login`).
- **Tests** → a login view, a sign-up view (root route), and a contact form, each
  asserting the output is server-side Flow Java (`package com.example`, `@Route`,
  `extends VerticalLayout`, the right components, no React/TS/markdown leakage).

## Prerequisites

- Node 20.20+ / 22.22+.
- `npm install` once in this directory — the Codex provider resolves
  `@openai/codex-sdk` from here.
- **Codex** signed in (`codex login`) and **Claude** signed in (`claude /login`).
  No `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` is needed — both default providers run on
  your subscription. You'd only set a key if you uncomment a key-based provider (e.g.
  `openai:gpt-4o-mini`).

## Run it

```bash
# Run the eval (prompts × providers × tests)
npx promptfoo@latest eval

# Open the results in the web viewer
npx promptfoo@latest view
```

`eval` prints a pass/fail table and exits non-zero if any assertion fails — so you
can drop the same command into CI to gate prompt changes.

## Make it yours

- **Change the prompt** → edit the `prompts:` block. Add a second item to A/B wordings.
- **Compare more models** → uncomment lines under `providers:` (e.g.
  `openai:gpt-4o-mini` needs `OPENAI_API_KEY`; `ollama:chat:llama3.2` needs none).
- **Add test cases** → add entries under `tests:`, or swap the block for
  `tests: tests.csv` (column headers become vars; a `__expected` column can hold an
  inline assertion).
- **Score differently** → mix assertion types: `contains`, `contains-all`, `regex`,
  `is-json`, `cost`, `latency`, `similar` (embeddings), `llm-rubric`, `factuality`,
  or custom `javascript`/`python`.

Docs: https://www.promptfoo.dev/docs/configuration/guide/
