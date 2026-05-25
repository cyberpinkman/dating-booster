# Dating Booster Agent-Native Launch Strategy

Status: accepted draft
Date: 2026-05-25

## Purpose

Dating Booster should support a lighter launch path before it becomes a full standalone agent. The current MVP can remain valuable as the standalone foundation, but the first practical product surface should also work as a skill, workflow pack, and local tool layer that enhances the user's existing agent.

This strategy avoids rebuilding what Codex, Claude Code, Hermes, OpenClaw, and similar hosts already provide: reasoning, tool orchestration, and computer use. Dating Booster should supply the dating-specific capability layer: memory, context packs, profile and conversation structure, policy checks, feedback, evals, and reusable workflows.

## Core Positioning

Dating Booster has two compatible product shapes:

1. **Agent-native capability layer**
   - The lightest launch path.
   - Runs through a host agent that already has LLM reasoning and computer-use ability.
   - Dating Booster provides skills, workflows, CLI tools, and later MCP tools.

2. **Standalone dating operator**
   - The mature full product.
   - Uses the same core modules but adds its own daemon, model backend, harness, UI, and autonomous execution loop.

The agent-native path comes first. The standalone path remains a future shell around the same reusable core.

## Strategic Correction

The MVP should not be deleted or rewritten. It should be reinterpreted as:

```text
dating_boost core + standalone-capable shell
```

The next layer should be:

```text
dating-booster skill/workflow + local tools
```

The core rule is no duplicated domain logic. Skill and workflow instructions can orchestrate tools, but they must not copy memory rules, content policy, context construction, or reply-mode behavior in a way that diverges from the core implementation.

## Target User Flow

Agent-native flow:

```text
user opens iPhone Mirroring
-> user accepts that the host agent may process visible dating-app context
-> user asks host agent to use Dating Booster workflow
-> host agent observes the dating app through its own computer-use tools
-> host agent calls Dating Booster local tools to update memory or build context
-> host agent drafts replies using its own model
-> Dating Booster checks draft content policy
-> host agent stages the draft in the app
-> user confirms high-risk send or enables autonomous mode
-> Dating Booster records feedback and memory updates
```

This path lets the user benefit immediately from Codex or another capable local agent without waiting for a complete Dating Booster daemon.

## Layering

### Core Library

The core library remains the source of truth.

Responsibilities:

- user profile schema.
- match profile schema.
- conversation memory.
- match identity resolution.
- memory provenance.
- context pack building.
- content policy.
- action policy.
- feedback events.
- eval contracts.
- normalized observations.

Core code must be host-agnostic and model-provider-agnostic.

### CLI Tools

The CLI is both a human surface and a host-agent tool surface.

Responsibilities:

- read and write local memory.
- ingest manual or fixture observations.
- build context packs.
- check draft content policy.
- record feedback.
- export and delete local data.
- run evals.

CLI output should prefer structured JSON for host-agent use. Human-readable output can be layered on top, but tool mode must remain stable.

### Skill and Workflow Pack

The skill/workflow layer teaches a host agent how to use Dating Booster.

Responsibilities:

- guide the host agent through dating workflows.
- call CLI tools in the correct order.
- tell the host agent when to observe, summarize, draft, stage, ask for confirmation, and record feedback.
- enforce the product boundary statement and high-risk action rules.
- prevent the host agent from bypassing Dating Booster memory and policy when those tools are available.

The skill does not own durable memory, schema definitions, or policy logic.

### MCP Adapter

MCP is the cleaner long-term host-agent integration.

Responsibilities:

- expose Dating Booster core tools as semantic MCP tools.
- avoid shell parsing for structured operations.
- give Codex, Claude Code, and other agents a stable tool surface.

MCP should follow the CLI contract rather than inventing new behavior.

### Standalone Shell

The standalone shell is a later product surface.

Responsibilities:

- run the local daemon.
- manage model backend settings.
- operate the macOS harness.
- provide desktop UI or menu bar controls.
- support background refresh.
- support complete local operator workflows.

It must reuse core modules and must not fork skill/workflow logic.

## Host Agent Responsibilities

In agent-native mode, the host agent provides:

- reasoning and planning.
- LLM generation.
- live computer use.
- screen observation when available.
- user interaction and clarification.
- final GUI staging or sending, subject to policy.

The host agent can draft natural language, but it should use Dating Booster context packs and policy checks when available.

## Dating Booster Responsibilities

Dating Booster provides:

- persistent dating memory.
- normalized observation ingestion.
- profile and conversation structure.
- context pack generation.
- reply mode metadata.
- content policy checks.
- action policy decisions.
- confirmation contract support.
- feedback capture.
- evals and regression fixtures.

Dating Booster should not assume it owns the model loop in agent-native mode.

## Host-Agent Privacy Notice

Agent-native mode intentionally relies on the user's chosen host agent. The host agent may see and process dating-app screen content, profile details, and conversation context while performing the workflow.

First-version CLI and skill support should not build heavy privacy enforcement around this. They should provide clear notice and let the user choose whether to run the experiment.

Rules:

1. The skill must tell the user that visible dating-app context may be processed by the host agent and its model provider.
2. Dating Booster should still minimize the structured context it writes to local memory and passes through local tools.
3. Dating Booster should not claim that host-agent processing is private unless the host agent's own terms and settings support that claim.
4. Stronger privacy controls belong to the standalone agent and daemon phase.

## First Skill Workflows

### Draft Reply Workflow

```text
1. Confirm the user wants Dating Booster assistance for the current dating app screen.
2. Observe the current app screen using host-agent computer use.
3. Convert visible information into a Dating Booster observation or manual input.
4. Run local tool: update or resolve match memory.
5. Run local tool: build context pack for the selected match and mode.
6. Host agent drafts best, safer, and bolder replies using the context pack.
7. Run local tool: content policy check for each draft.
8. Present allowed drafts and policy notes to the user.
9. Stage the selected draft if requested.
10. Record user feedback.
```

### Profile Refresh Workflow

```text
1. Ask the user to navigate or allow the host agent to navigate to the match profile.
2. Observe profile text and visible photo cues.
3. Convert observations into structured input.
4. Run local tool: update match profile.
5. Report confidence, new hooks, conflicts, and missing information.
```

### High-Risk Send Workflow

```text
1. Confirm the draft text, target match, and latest visible message.
2. Run local tool: action policy check.
3. If confirmation is required, ask the user to explicitly confirm.
4. Host agent stages or sends only the confirmed payload.
5. Host agent observes the screen again after the action.
6. Run local tool: record action result with post-action evidence.
7. Record audit and feedback events.
```

### Host-Executed Action Verification

In agent-native mode, the host agent performs GUI actions. Dating Booster must not assume those actions succeeded.

For each staged or high-risk host-executed action, the host should provide:

- `action`: semantic action name.
- `target_match_id`: target match when known.
- `payload_hash`: hash of the confirmed payload.
- `pre_action_observation_id`: observation used for confirmation.
- `post_action_observation`: fresh observation after the host action.
- `result_status`: succeeded, failed, or unknown.
- `evidence`: visible post-action evidence, such as draft text in input box, sent bubble, latest message, or unchanged screen.

Rules:

1. If the host cannot re-observe the screen, result status is `unknown`.
2. If target match or latest visible message changed unexpectedly, result status is `unknown` or `failed`.
3. Memory must not record a send as successful unless post-action evidence supports it.
4. Audit logs should include failed and unknown results, not just successes.
5. Unknown results should stop the workflow and ask the user what happened.

## Local Tool Contract

Agent-native tools should be small and composable.

Initial CLI commands:

- `dating-boost capabilities --json`
- `dating-boost memory ingest-observation`
- `dating-boost memory get-match`
- `dating-boost memory update-match`
- `dating-boost context build`
- `dating-boost policy check-draft`
- `dating-boost policy check-action`
- `dating-boost feedback record`
- `dating-boost eval run`
- `dating-boost export`
- `dating-boost delete`

All commands should support JSON input and JSON output.

The command names can change during implementation, but the capability boundaries should remain.

### Capability Discovery and Versioning

The skill must check local tool compatibility before starting a workflow.

`dating-boost capabilities --json` should return:

- `tool_version`: Dating Booster CLI version.
- `git_commit`: current Dating Booster source commit when available.
- `schema_versions`: supported input and output schema versions.
- `supported_commands`: commands available in this checkout.
- `data_dir`: local data directory path.
- `policy_capabilities`: content policy, action policy, confirmation, and action-result recording support.
- `memory_capabilities`: observation ingest, match profile, conversation memory, feedback, export, and delete support.
- `agent_native_capabilities`: features intended for host-agent workflows.
- `warnings`: setup, migration, or compatibility warnings.

Rules:

1. The skill should call capabilities before relying on any command.
2. If the required command or schema version is missing, the skill should stop and report the mismatch.
3. Skill packages should declare `dating_boost_min_version`.
4. Skill packages should record the source spec commit or release they were generated from.
5. CLI JSON output should include `schema_version` for machine-readable commands.

## Skill Packaging

The first skill package should contain:

- `SKILL.md`: workflow instructions for host agents.
- `skill-package.json`: package metadata and compatibility requirements.
- `references/boundary-statement.md`: product and platform-risk language, kept in sync with README.
- `references/reply-modes.md`: concise Self, Adaptive, and Recipient-Optimized guidance that points back to the intelligence spec as source of truth.
- `references/safety-policy.md`: concise hard facts, consent, persona, stance, and content policy guidance that points back to core policy contracts.
- `references/workflows.md`: draft, profile refresh, send, feedback, and memory workflows that call local tools rather than reimplementing logic.
- `examples/`: example context packs, draft outputs, and policy check outputs.

The skill should instruct host agents to prefer local Dating Booster tools when available and to fail clearly when a required tool is missing. Reference files are operational summaries; core code and committed specs remain the source of truth.

`skill-package.json` should include:

- `package_name`: dating-booster-codex-skill.
- `package_version`: skill package version.
- `target_host`: codex for the first package.
- `dating_boost_min_version`: minimum compatible Dating Booster CLI version.
- `required_schema_versions`: schema versions required by the skill.
- `source_spec_commit`: git commit or release tag used to generate the skill package.
- `source_specs`: spec files used as source of truth.
- `required_commands`: CLI commands the skill expects.

Compatibility rules:

1. At workflow startup, the skill calls `dating-boost capabilities --json`.
2. The skill compares `tool_version`, `schema_versions`, and `supported_commands` against `skill-package.json`.
3. If the local tool is too old, missing commands, or missing required schema versions, the skill stops before observing dating-app content.
4. If `source_spec_commit` differs from the local repo commit, the skill reports a warning. It can continue only if version and schema checks pass.
5. Generated skill packages should update `skill-package.json` in the same commit as any workflow reference changes.

## Skill Target Decision

The workflow concepts should remain host-agnostic, but the first packaged skill should be Codex-first.

Rationale:

1. The current concrete user path is Codex plus iPhone Mirroring plus computer use.
2. Host skill formats, tool names, permission models, and computer-use affordances differ.
3. A Codex-first package can validate the real workflow faster.
4. The underlying CLI JSON contracts and workflow vocabulary remain reusable for Claude Code, Hermes, OpenClaw, and MCP adapters.

Decision:

- Build the first package for Codex.
- Write workflow references in generic language where possible.
- Keep host-specific instructions isolated in the package entrypoint.
- Treat other host packages as adapters over the same local tools, not as separate product logic.

## Relationship to Product Blueprint

This launch strategy does not replace the product architecture blueprint. It adds a lighter first surface.

Mapping:

- Product blueprint `Core Library` maps to Dating Booster reusable modules.
- Product blueprint `CLI` becomes the first local tool surface.
- Product blueprint `MCP Adapter` becomes the second host-agent integration.
- Product blueprint `Standalone Shell` remains future daemon/UI/operator.
- Product blueprint `Perception` can start with host-agent observation before Dating Booster owns live perception.

## Relationship to Current MVP

The current MVP is still useful if it keeps these properties:

1. Core modules are importable and do not require a standalone run loop.
2. CLI commands can be used by another agent.
3. Model backend use is optional or isolated behind interfaces.
4. Memory and policy do not depend on GUI harness code.
5. Eval fixtures can test core behavior without live Tinder.

If an MVP component assumes Dating Booster owns the whole agent loop, it should be wrapped or refactored later, not immediately discarded.

## Launch Sequence

### Phase A: Agent-Native Skill

Goal: make Dating Booster useful inside Codex or another host agent immediately.

Deliverables:

- skill/workflow documentation.
- CLI JSON contracts for context, policy, memory, and feedback.
- `dating-boost capabilities --json`.
- examples for draft and profile refresh workflows.
- README section explaining agent-native mode.

### Phase B: MCP Tools

Goal: remove fragile shell command orchestration.

Deliverables:

- MCP server exposing semantic Dating Booster tools.
- tool schemas aligned with CLI JSON contracts.
- host-agent examples.

### Phase C: Standalone Operator

Goal: support users who do not want to orchestrate through Codex or another agent.

Deliverables:

- daemon.
- local UI or menu bar controls.
- model backend configuration.
- live iPhone Mirroring harness.
- confirmation and audit UX.

## Non-Goals

- Do not fork separate logic for skill mode and standalone mode.
- Do not expose raw GUI primitives through the skill or MCP layer.
- Do not require Dating Booster to call an LLM in agent-native mode.
- Do not make the skill responsible for durable memory.
- Do not use mock workflows as the primary product path.
- Do not treat host-agent convenience as permission from target dating apps.

## Open Questions

1. Whether CLI JSON contracts should be finalized before writing the skill.
2. Whether examples should use synthetic dating data, redacted real data, or both.
3. Whether the first MCP adapter should be built before or after screenshot fixture perception.
