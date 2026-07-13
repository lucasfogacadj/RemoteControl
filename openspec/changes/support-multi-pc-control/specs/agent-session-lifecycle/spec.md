## ADDED Requirements

### Requirement: The hub maintains one live session registry per agent

The hub SHALL represent connected agents as `agent_id -> session` entries. Each session SHALL have a unique `session_id`, a session generation, its WebSocket, heartbeat timestamp, and an independent send lock. Sessions for different agent IDs SHALL coexist.

#### Scenario: Two PCs connect simultaneously

- **WHEN** `agent-a` and `agent-b` establish WebSocket connections
- **THEN** both sessions remain connected in the registry
- **AND** a command sent to one session cannot be sent through the other session

#### Scenario: Reconnect replaces only the same agent

- **WHEN** a second session for `agent-a` connects
- **THEN** the old `agent-a` session is invalidated and only `agent-a`'s generation changes
- **AND** the live session for `agent-b` remains unchanged

### Requirement: Agent identity and hello metadata are validated

The new Windows agent SHALL require `CONTROL_AGENT_ID` and SHALL validate it before connecting. Its hello message SHALL include `agent_id`, `name`, `version`, `protocol`, `dry_run`, and a server-consumable list of `capabilities`. The hub SHALL retain a compatibility path for the legacy protocol without treating an omitted legacy field as a new arbitrary agent.

#### Scenario: Valid hello creates a known protocol session

- **WHEN** an agent sends a valid hello with its identity and capability metadata
- **THEN** the hub records the metadata for that agent and session
- **AND** subsequent commands and results are correlated to that session generation

#### Scenario: Missing identity cannot connect as a new PC

- **WHEN** a new agent omits `CONTROL_AGENT_ID` or sends an invalid ID
- **THEN** the hub closes or rejects the WebSocket with a protocol error
- **AND** it does not allocate settings or commands under a guessed default shared by other PCs

### Requirement: Heartbeat and online state are session-aware

The hub SHALL update heartbeat state only when the message belongs to the current session generation for that `agent_id`. Online state SHALL require a live, non-stale WebSocket; persisted heartbeat data alone SHALL not make an agent online.

#### Scenario: Stale session heartbeat is ignored

- **WHEN** an old session sends a heartbeat after a newer session for the same agent is active
- **THEN** the hub does not advance the newer session's heartbeat timestamp
- **AND** it does not mark the old session online

#### Scenario: Different agents have independent heartbeat expiry

- **WHEN** `agent-a` stops heartbeating and `agent-b` continues
- **THEN** only `agent-a` becomes stale/offline
- **AND** `agent-b` remains online and schedulable if its other gates permit

### Requirement: Sending is serialized per session and conditionally cleaned up

The hub SHALL serialize sends through a lock owned by the target agent session. A send failure SHALL clear or invalidate only the session that failed if it is still the current generation; it SHALL not clear a newer replacement session or another agent.

#### Scenario: Concurrent control and command sends do not interleave

- **WHEN** a cancel message and a command are sent concurrently to the same agent
- **THEN** the session lock emits complete messages in a deterministic serialized order
- **AND** neither message is written to another agent's socket

#### Scenario: Old send failure cannot tear down a replacement

- **WHEN** a send on an old session fails after a replacement session has connected
- **THEN** conditional cleanup leaves the replacement session registered
- **AND** the scheduler may continue only according to the replacement session's state

### Requirement: Execution survives connection teardown until terminal cleanup

The agent execution slot SHALL live outside the WebSocket receive loop. A socket loss, watchdog expiry, or reconnect SHALL signal cancellation to the active command and SHALL wait for the worker to reach a terminal state before another command for that same agent is accepted.

#### Scenario: Socket drops during a routine

- **WHEN** the WebSocket closes while `agent-a` is executing `command-1`
- **THEN** the hub and agent request cooperative cancellation for `command-1`
- **AND** no orphaned worker continues as an accepted active command after teardown
- **AND** a reconnect for `agent-a` cannot start `command-2` until `command-1` is terminal

#### Scenario: Different PCs execute in parallel

- **WHEN** `agent-a` and `agent-b` each receive one valid command
- **THEN** their execution slots may run concurrently
- **AND** busy state or cancellation on one PC does not reject or cancel the other PC's command

### Requirement: Results are correlated and late results are harmless

The hub SHALL accept a result only when `command_id`, `agent_id`, and `session_id` match the command's current ownership and the result state is known. Results for cancelled, timed-out, replaced-session, or unknown commands SHALL be recorded as `late_result` or rejected without changing a terminal command to success.

#### Scenario: Result from another PC is rejected

- **WHEN** `agent-b` submits a result using a command ID owned by `agent-a`
- **THEN** the hub records the correlation failure for audit
- **AND** it leaves `agent-a`'s command status unchanged

#### Scenario: Cancelled command cannot become successful

- **WHEN** the hub has conditionally marked `command-1` cancelled and a delayed success arrives from its old session
- **THEN** the event is classified as `late_result`
- **AND** `command-1` remains cancelled

#### Scenario: Unknown result state is not terminal success

- **WHEN** a result contains a state outside the accepted result-state set
- **THEN** the hub rejects or audits it as invalid
- **AND** it does not persist the unknown state as a successful command result
