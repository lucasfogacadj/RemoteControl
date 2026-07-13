## ADDED Requirements

### Requirement: Fleet and agent activation are independent gates

The hub SHALL persist one fleet-level master switch and one `enabled` flag per agent. A command SHALL be eligible for execution only when the fleet is active, the target agent is enabled, and the target agent is inside its configured work window.

#### Scenario: Master switch pauses every agent

- **WHEN** the fleet master switch changes to inactive
- **THEN** no agent may receive a new command
- **AND** active commands for every agent are cooperatively cancelled

#### Scenario: Individual toggle isolates one agent

- **WHEN** `agent-a` is disabled while `agent-b` remains enabled and the fleet is active
- **THEN** `agent-a` stops receiving commands and its active command is cancelled
- **AND** `agent-b` remains eligible to schedule and execute its own command

### Requirement: New agents are registered disabled by default

The hub SHALL create an agent record when a valid previously unknown `agent_id` completes connection setup. The new record SHALL start with `enabled=false`, default settings, and no permission to receive a command until explicitly enabled.

#### Scenario: First connection onboards a PC

- **WHEN** a valid new agent identifies itself as `windows-desktop-02`
- **THEN** the hub creates its per-agent settings and state without changing the fleet master switch
- **AND** the new agent is reported as disabled
- **AND** no command is dispatched to it before an explicit enable operation

#### Scenario: Invalid or colliding identity is rejected

- **WHEN** an agent presents an empty, malformed, or already-conflicting `agent_id`
- **THEN** the hub rejects the connection setup with an auditable protocol error
- **AND** it does not overwrite another agent's settings, state, session, or command

### Requirement: Fleet state is available through an agent-scoped API

The hub SHALL expose `GET /api/fleet/state` with the master switch, scheduler/watchdog summary, and a summary for every registered agent. It SHALL expose `GET /api/agents/{agent_id}/state` for the explicit selected agent and SHALL return a not-found response for an unknown ID rather than falling back to another agent.

#### Scenario: Fleet summary lists multiple PCs

- **WHEN** two or more agents are registered with different online and enabled states
- **THEN** `GET /api/fleet/state` returns each agent exactly once with its own connectivity, settings revision, active command, and schedule summary
- **AND** the response identifies the fleet master state independently from each agent state

#### Scenario: Detail endpoint never follows the last heartbeat

- **WHEN** the last heartbeat belongs to `agent-b` and the client requests `/api/agents/agent-a/state`
- **THEN** the response contains only `agent-a` data
- **AND** no field is substituted from `agent-b`

### Requirement: Agent settings use optimistic concurrency

The hub SHALL expose `PUT /api/agents/{agent_id}/settings`. A full settings replacement SHALL require the current revision through `ETag` or an equivalent revision precondition, SHALL validate the complete payload before writing, and SHALL return the new revision and `ETag` after success.

#### Scenario: Settings update with current revision succeeds

- **WHEN** a client submits a valid complete settings document with the current revision for `agent-a`
- **THEN** only `agent-a` settings are replaced
- **AND** the revision increments atomically
- **AND** the scheduler for `agent-a` is notified to reset its rhythm state

#### Scenario: Stale settings update is rejected

- **WHEN** a client submits a valid document with a revision older than the stored revision
- **THEN** the hub returns a conflict/precondition response
- **AND** it leaves the stored settings and revision unchanged
- **AND** it includes enough current-version information for the client to reload safely

### Requirement: Agent controls are narrowly scoped

The hub SHALL expose `POST /api/agents/{agent_id}/toggle` and `POST /api/agents/{agent_id}/cancel`. The toggle operation SHALL change only the target agent's `enabled` value. The cancel operation SHALL affect only commands belonging to the target agent and SHALL be idempotent when no active command exists.

#### Scenario: Toggle does not replace settings

- **WHEN** a client toggles `agent-a` from disabled to enabled
- **THEN** the response reports the new enabled value
- **AND** every other settings field and revision remains unchanged
- **AND** `agent-b` is unchanged

#### Scenario: Cancel is isolated and idempotent

- **WHEN** `agent-a` has an active command and `agent-b` has a different active command
- **THEN** cancelling `agent-a` sends cancellation only to `agent-a` and marks only its command for cooperative cancellation
- **AND** `agent-b` continues independently
- **AND** repeating the cancel request does not create a new command or error caused by the first cancellation

### Requirement: Scoped history endpoints support cursors

The hub SHALL expose `GET /api/events?agent_id=...&cursor=...` and `GET /api/commands?agent_id=...&cursor=...`. When `agent_id` is supplied, every returned row SHALL belong to that agent; cursor pagination SHALL be stable and SHALL not duplicate rows when new rows are appended.

#### Scenario: History is isolated by agent

- **WHEN** events and commands exist for `agent-a`, `agent-b`, and legacy-unassigned rows
- **THEN** a query for `agent-a` returns only `agent-a` rows
- **AND** a query without an agent filter follows the documented fleet/legacy behavior without silently attributing legacy rows to a PC

#### Scenario: Cursor continues after new activity

- **WHEN** a client requests the next page using the cursor from a previous response and another event is inserted
- **THEN** the next page continues after the cursor according to the documented `(created_at,id)` order
- **AND** rows already delivered are not repeated

### Requirement: Legacy API aliases remain explicit

The hub SHALL preserve `POST /api/toggle` as the fleet master kill switch. It SHALL preserve `/api/state` and `/api/settings` temporarily as aliases for the explicit legacy agent `windows-desktop-01`; those aliases MUST NOT resolve to the most recently connected or most recently heartbeating agent.

#### Scenario: Legacy alias targets the migrated PC

- **WHEN** `windows-desktop-02` connects after `windows-desktop-01`
- **THEN** `/api/state` and `/api/settings` still read and write only `windows-desktop-01`
- **AND** the legacy request cannot mutate `windows-desktop-02`

#### Scenario: Legacy master toggle remains global

- **WHEN** a legacy client posts an inactive value to `/api/toggle`
- **THEN** the fleet master switch becomes inactive
- **AND** all agent schedulers observe the global pause and cancel their eligible active commands
