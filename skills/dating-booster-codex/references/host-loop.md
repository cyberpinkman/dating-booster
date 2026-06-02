# Tinder Host Loop

Use this workflow when the user wants Codex to run a real Tinder host loop with
iPhone Mirroring. This is not a native GUI harness: `dating-boost` drives the
operator state machine and Codex performs observation, paste, click, and
verification.

## Start

Run:

```bash
dating-boost-host-loop \
  --data-dir .local/dating-boost \
  --authorization auth.json \
  --goal goal.json \
  --availability availability.json \
  --app-id tinder \
  --send-mode stage \
  --work-dir .local/dating-boost-host-loop \
  --json
```

When running from a cloned repository, `python3 scripts/operator_host_loop.py`
is a compatibility wrapper around the same command.

Use `--send-mode stage` by default. It stages text in the input box and stops
before sending. Use `--send-mode live` only after the user explicitly authorizes
ordinary automatic sends.

## Work Items

The supervisor writes `current_work_item.json` and a template for the host to
fill. The host writes the non-template JSON file back into the same work dir.

- `scan_message_list`: open the Tinder message list and write
  `message_list_observation.json`. Candidate keys should follow
  `visible_name + row_index + latest_preview_hash`.
- `open_thread`: open the requested thread and write
  `thread_observation_<candidate_key>.json` with `latest_inbound_messages`,
  `planner_assessment`, and a draft only when the planner move needs a reply.
- `send_message`: paste `payload_text`, verify it, and write
  `staged_verification.json`.

In `stage` mode, do not click send after `staged_verification.json`; stop and
ask the user whether to send. In `live` mode, click send only after staged text
verification succeeds, then observe the sent bubble and write
`action_result.json`.

## iPhone Mirroring Rules

- Re-locate the current input box before every click; never reuse stale
  coordinates after layout changes.
- Tinder Chinese text should be pasted, not typed directly.
- Verify staged text exactly equals `payload_text`.
- If the input box position drifts after full-screen input, exit and reopen the
  chat thread instead of repeatedly clicking the old position.
- If paste/menu interaction fails once, retry once; if it still fails, stop with
  `unknown` or stage-mode waiting rather than pretending success.
- A send is `succeeded` only when a fresh observation shows the sent bubble.

Handoff immediately for specific date/time/place, contact exchange, profile
changes, likes, unmatches, reports, or any high-risk action.
