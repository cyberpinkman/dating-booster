# Tinder Host Loop

Use this workflow when the user wants Codex to run a real Tinder host loop with
iPhone Mirroring. `dating-boost-host-loop` drives the operator state machine.
`dating-boost harness ...` provides the native stage/navigation harness for
iPhone Mirroring diagnostics, screenshots/OCR, safe Tinder profile-tab
navigation, profile reading, chat/profile opening chains, and gated managed
send. Codex still performs semantic screen understanding and must verify staged
text and outbound post-action evidence before any managed send is recorded.

## Start

Run doctor first:

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder open-profile --launch-if-needed --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --photo-steps 2 --scroll-steps 2 --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --conversation-row 1 --profile-scroll-steps 2 --json
dating-boost harness tinder workflow new-match-open --dry-run --carousel-swipes 1 --match-index 2 --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --carousel-swipes 1 --match-index 2 --profile-scroll-steps 2 --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
dating-boost-host-loop doctor \
  --data-dir .local/dating-boost \
  --app-id tinder \
  --json
```

Use `harness tinder observe` before selecting an action or workflow. Use the
workflow commands only as dry-run plans until a fresh observation confirms the
current Tinder page matches the expected starting state. They are
navigation-only reading/profile-refresh/open-thread chains. Use
`chat-read-match-profile` only for existing message rows. Use `new-match-open`
or `new-match-read-profile` for unopened matches; after a gated opener send,
run `harness tinder action return-to-chats` before selecting the next unopened
match. A real send is allowed only via `harness tinder send-message` or
`--managed-gui-send` with explicit live-send authorization, a policy-checked
action request, target-chat binding, staged text verification, outbound-bubble
verification, and an unpaused safety switch. The harness never authorizes like,
super-like, unmatch, report, or profile edit actions.

If configuration files are missing, generate templates:

```bash
dating-boost-host-loop init \
  --data-dir .local/dating-boost \
  --work-dir .local/dating-boost-host-loop \
  --app-id tinder \
  --json
```

Run the loop:

```bash
dating-boost-host-loop run \
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

Resume/status helpers:

```bash
dating-boost-host-loop status --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --json
dating-boost-host-loop resume --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost-host-loop confirm-staged --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --json
```

Use `--send-mode stage` by default. It stages text in the input box and stops
before sending. Use `--send-mode live` only after the user explicitly authorizes
ordinary automatic sends.

## Work Items

The supervisor writes `current_work_item.json` and a template for the host to
fill. The host writes the non-template JSON file back into the same work dir.
All active input files are scoped by `work_item_id` so stale files cannot
pollute a resumed run.

- `scan_message_list`: open the Tinder message list and write
  `message_list_observation.<work_item_id>.json`. Candidate keys should follow
  `visible_name + row_index + latest_preview_hash`.
- `open_thread`: open the requested thread and write
  `thread_observation.<work_item_id>.json` with `latest_inbound_messages`,
  `planner_assessment`, and a draft only when the planner move needs a reply.
- `send_message`: paste `payload_text`, verify it, and write
  `staged_verification.<work_item_id>.json`.

In `stage` mode, do not click send after `staged_verification.<work_item_id>.json`; stop and
ask the user whether to send. In `live` mode, click send only after staged text
verification succeeds, then observe the sent bubble and write
`action_result.<work_item_id>.json`.

For compatibility with older examples, the unscoped names
`message_list_observation.json`, `thread_observation_<candidate_key>.json`,
`staged_verification.json`, and `action_result.json` may appear in old docs.
Phase C host loop uses scoped file names.

Before ingesting a host-authored observation, validate it:

```bash
dating-boost observation validate --input OBSERVATION.json --json
```

Thread observations must include `turn_boundary_evidence`,
`identity_confidence`, `identity_evidence`, and `screenshot_ref` (empty string
allowed). `latest_inbound_messages` must contain only messages after the
user's latest outbound; old visible messages are background.

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

## Replay And Eval

After a run:

```bash
dating-boost replay latest --data-dir .local/dating-boost --format md
dating-boost eval run --suite conversation --json
```

The replay timeline records work items, observations, staged verification,
action results, and final state. The conversation eval is deterministic fixture
regression; it does not call an external model.
