---
name: dating-booster-codex
description: Codex-first workflow for using Dating Booster as local memory, context, policy, and audit tools for dating-app assistance.
---

# Dating Booster Codex Workflow

Use this skill when the user asks Codex to assist with dating-app workflows through Dating Booster local tools.

## Mandatory Capability Check

Before observing any dating app screen, visible dating app content, screenshots, or conversation text, choose a local data directory for this workflow. Prefer `.local/dating-boost` unless the user gives another path. Then run:

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
```

Load this package's `skill-package.json` and compare it with the capabilities JSON before continuing:

- `tool_version` must be greater than or equal to `dating_boost_min_version`.
- Every `required_schema_versions` entry must exist in `schema_versions` with the same version.
- Every `required_commands` entry must exist in `supported_commands`.
- `schema_version` for capabilities must be supported by this skill package.
- If `source_spec_commit` differs from the local repo commit, report a warning. Continue only if version, schema, and command checks pass.

If the command is missing, returns invalid JSON, has an incompatible `schema_version`, is too old, lacks a required schema version, or does not list the required commands, stop before observing dating app content and tell the user the local Dating Booster tool is incompatible.

## Privacy Boundary

In this mode, Codex is the host agent. The host agent may process visible dating app content, screenshots, profile text, conversation text, and generated drafts. Dating Booster stores local memory, context, policy decisions, feedback, and action audit records; it does not own the LLM in this workflow.

## Default Action Policy

Allowed by default:

- Observe visible screen content after the capability check and user intent are clear.
- Summarize profile or conversation context.
- Run `dating-boost workflow draft` after the host agent has authored an observation JSON and draft JSON.
- Build context with `dating-boost context build` when debugging or using lower-level commands.
- Draft replies inside the host agent.
- Check drafts with `dating-boost policy check-draft`.
- Paste a draft only when the user requested it.

High-risk actions require explicit user confirmation and the local policy switch:

- Sending a message.
- Liking, super-liking, unmatching, reporting, or editing profile data.
- Proposing a meeting or exchanging contact details.

Do not treat autonomous mode as permission to bypass app rules, rate limits, verification, account restrictions, or user judgment.

## Default Draft Output

Naturalness review is an internal QA step. Before showing any draft, silently apply
`references/naturalness-checklist.md` and revise the draft if needed.

By default, show only the final draft and at most a small number of alternatives.
Do not show checklist results, validation notes, or reasoning about why the draft
does or does not trigger specific checklist items. Show that material only when
the user explicitly asks for explanation, critique, review, or debug output.

## Workflow

1. Run `dating-boost capabilities --json --data-dir .local/dating-boost` and verify compatibility against `skill-package.json`.
2. Convert visible screen content to an observation JSON using `references/observation-authoring.md`.
3. Read `references/drafting-framework.md`, then generate the draft JSON in Codex using the visible profile/chat context.
4. Before using the draft, silently apply `references/naturalness-checklist.md` and revise anything that reads like AI-written Chinese.
5. Run `dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive`.
6. If the workflow returns `blocked`, do not show or paste the blocked draft.
7. If the workflow returns `ok`, show only the final draft or paste it when the user requested paste.
8. For any high-risk action, run `dating-boost policy check-action` and ask for explicit confirmation.
9. After the host executes an action, perform post-action verification from a fresh observation.
10. Record the result with `dating-boost action record-result`.
11. Record user feedback with `dating-boost feedback record` when useful.

Use `references/workflows.md` for reusable workflow details and lower-level command fallbacks, `references/contracts.md` for JSON input/output contract examples, and the drafting/naturalness references for Chinese reply quality. These reference files are summaries; core code and committed specs remain the source of truth.

## Post-Action Verification

For sent messages or other high-risk actions, do not record success unless the post-action observation confirms the expected state. If the result cannot be verified, record `result_status` as `unknown`, not `succeeded`.

## Prohibited

- Private APIs, reverse engineering, or non-GUI service automation.
- Account farming, bulk swiping, scraping member-only data, or evading bans/checks.
- Claiming an action succeeded without post-action verification.
- Leaking a draft that `dating-boost policy check-draft` blocks.
