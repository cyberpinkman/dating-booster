# Tinder Host Loop Stability Spec

## Summary

The first live stability layer is a host loop supervisor, not a native macOS
harness. The supervisor drives `operator next`; the host agent observes Tinder
through iPhone Mirroring, authors JSON observations, executes paste/send actions,
and writes verification results back to disk.

The default mode is `stage`: prepare and verify a message in the input box but
do not click send. `live` mode is explicit and still requires staged text
verification before clicking send and recording an action result.

## Supervisor

`dating-boost-host-loop` supports:

- `--data-dir`
- `--authorization`
- `--goal`
- `--availability`
- `--app-id tinder`
- `--send-mode stage|live`
- `--work-dir`
- `--max-steps`
- `--once`
- `--json`
- `--fixture-host`

The supervisor performs capability, skill doctor, readiness, authorization,
goal, and availability checks before starting an operator session.

## Work Directory Contract

The supervisor writes:

- `current_work_item.json`
- `message_list_observation.template.json`
- `thread_observation_<candidate_key>.template.json`
- `staged_verification.template.json`
- `action_result.template.json`

The host writes:

- `message_list_observation.json`
- `thread_observation_<candidate_key>.json`
- `staged_verification.json`
- `action_result.json`

Processed host inputs are moved into `consumed/`.

## Tinder Rules

- Re-locate the current input box before every click.
- Use paste for Chinese text; do not depend on direct Chinese typing.
- Verify staged text exactly equals `payload_text`.
- If input position drifts, leave and reopen the thread instead of repeatedly
  clicking stale coordinates.
- Record `succeeded` only after a fresh post-action observation confirms a sent
  bubble.
- Exact meeting details, contact exchange, and high-risk actions remain handoff.
