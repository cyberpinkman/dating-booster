---
name: dating-booster-codex
description: Codex-first workflow for using Dating Booster as local memory, context, policy, and audit tools for dating-app assistance.
---

# Dating Booster Codex Workflow

Use this skill when the user asks Codex to assist with dating-app workflows through Dating Booster local tools.

## Mandatory Capability Check

Before observing any dating app screen, visible dating app content, screenshots, or conversation text, run:

```bash
dating-boost capabilities --json
```

If the command is missing, returns invalid JSON, has an incompatible `schema_version`, lacks a required schema version, or does not list the required commands, stop before observing dating app content and tell the user the local Dating Booster tool is incompatible.

## Privacy Boundary

In this mode, Codex is the host agent. The host agent may process visible dating app content, screenshots, profile text, conversation text, and generated drafts. Dating Booster stores local memory, context, policy decisions, feedback, and action audit records; it does not own the LLM in this workflow.

## Default Action Policy

Allowed by default:

- Observe visible screen content after the capability check and user intent are clear.
- Summarize profile or conversation context.
- Build context with `dating-boost context build`.
- Draft replies inside the host agent.
- Check drafts with `dating-boost policy check-draft`.
- Paste a draft only when the user requested it.

High-risk actions require explicit user confirmation and the local policy switch:

- Sending a message.
- Liking, super-liking, unmatching, reporting, or editing profile data.
- Proposing a meeting or exchanging contact details.

Do not treat autonomous mode as permission to bypass app rules, rate limits, verification, account restrictions, or user judgment.

## Workflow

1. Run `dating-boost capabilities --json` and verify compatibility.
2. Ingest or update observations with `dating-boost memory ingest-observation` after screen content is available.
3. Retrieve match memory with `dating-boost memory get-match`.
4. Build the context pack with `dating-boost context build`.
5. Generate the draft in Codex using the user profile, match profile, and conversation context.
6. Run `dating-boost policy check-draft` before showing or using the draft.
7. For any high-risk action, run `dating-boost policy check-action` and ask for explicit confirmation.
8. After the host executes an action, perform post-action verification from a fresh observation.
9. Record the result with `dating-boost action record-result`.
10. Record user feedback with `dating-boost feedback record` when useful.

## Post-Action Verification

For sent messages or other high-risk actions, do not record success unless the post-action observation confirms the expected state. If the result cannot be verified, record `result_status` as `unknown`, not `succeeded`.

## Prohibited

- Private APIs, reverse engineering, or non-GUI service automation.
- Account farming, bulk swiping, scraping member-only data, or evading bans/checks.
- Claiming an action succeeded without post-action verification.
- Leaking a draft that `dating-boost policy check-draft` blocks.
