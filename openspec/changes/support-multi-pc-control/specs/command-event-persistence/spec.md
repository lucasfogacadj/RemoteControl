## ADDED Requirements

### Requirement: SQLite schema changes are versioned and transactional

The hub SHALL track migration versions and SHALL apply each migration atomically. The multi-PC migration SHALL be idempotent, safe to retry after a clean interruption, and SHALL not report readiness while required migrations are incomplete.

#### Scenario: Migration runs once on the current database

- **WHEN** the existing single-agent database is opened for the first time after the change
- **THEN** the migration creates the fleet and agent-scoped structures in one transaction
- **AND** a second startup does not duplicate rows, indexes, or migration effects

#### Scenario: Interrupted migration can be retried

- **WHEN** the process stops during migration and restarts with the same database
- **THEN** the migration resumes or rolls back to a consistent version
- **AND** no partially written settings or commands are exposed as valid state

### Requirement: First migration creates a consistent backup and integrity evidence

Before applying the first multi-PC schema migration, the hub SHALL create a consistent SQLite backup through the SQLite backup API and SHALL run `integrity_check` on the relevant source/backup databases. Failure SHALL block migration and readiness.

#### Scenario: Backup is restorable before schema changes

- **WHEN** the pre-migration backup completes
- **THEN** the backup can be opened independently and passes integrity validation
- **AND** the original database is not modified until the backup step succeeds

#### Scenario: Backup or integrity failure aborts migration

- **WHEN** the backup cannot be created or `integrity_check` reports corruption
- **THEN** the hub leaves the application data untouched
- **AND** it exposes an actionable readiness failure

### Requirement: Agent-scoped persistence preserves legacy rows

The schema SHALL provide `fleet_state` for the global master switch and `agent_settings` keyed by `agent_id`, including validated settings JSON, `enabled`, `revision`, and timestamps. The current singleton configuration SHALL be migrated to `windows-desktop-01`. Existing commands and events without an agent SHALL remain as legacy-unassigned rows, and legacy active commands SHALL be cancelled during migration.

#### Scenario: Current settings are assigned deterministically

- **WHEN** the legacy singleton settings row exists during migration
- **THEN** its validated content is copied to `windows-desktop-01`
- **AND** the legacy API alias resolves to that explicit agent

#### Scenario: Migration keeps the new fleet master paused

- **WHEN** the first multi-PC migration creates `fleet_state`
- **THEN** the global master switch starts disabled regardless of the legacy PC activation bit
- **AND** the legacy activation bit is migrated only to `windows-desktop-01`
- **AND** no agent can execute until the operator explicitly reactivates the fleet after dry-run validation

#### Scenario: Legacy active command is not executed after migration

- **WHEN** a pre-migration command has an active status and no `agent_id`
- **THEN** migration marks it cancelled with an auditable reason
- **AND** it cannot be dispatched or converted into a successful result later

### Requirement: Commands and events carry ownership metadata

The command store SHALL support `agent_id`, `session_id`, and `deadline_at`. The event store SHALL support `agent_id` and `command_id`. Rows without those fields SHALL be treated as legacy-unassigned, not inferred from the last heartbeat. Queries SHALL have indexes for agent, status, and date/cursor access.

#### Scenario: Command ownership survives reconnect

- **WHEN** a command is dispatched in session `s1` and the same agent reconnects as `s2`
- **THEN** the command remains owned by its original `agent_id` and `s1`
- **AND** a result from `s2` cannot silently overwrite the command without the defined late-result handling

#### Scenario: Legacy rows are visible without false attribution

- **WHEN** a history query includes legacy rows
- **THEN** those rows expose a null/legacy ownership marker
- **AND** the API does not assign them to whichever PC is currently online

### Requirement: The database enforces one active command per agent

The persistence layer SHALL enforce at most one command in an active status for each non-null `agent_id`, including concurrent creation attempts. A rejected duplicate SHALL leave the previously active command unchanged.

#### Scenario: Concurrent scheduler attempts race safely

- **WHEN** two scheduler tasks attempt to create active commands for the same agent at the same time
- **THEN** at most one insert/update succeeds
- **AND** the loser observes a busy/duplicate condition without creating a second active row

#### Scenario: Different agents can have active commands

- **WHEN** one active command exists for `agent-a` and another is created for `agent-b`
- **THEN** both rows are accepted
- **AND** their status, deadlines, and results remain independently addressable

### Requirement: Command state updates are conditional and terminal-safe

The store SHALL accept only known command/result states and SHALL update rows conditionally by command ownership and expected current status. Once a command is cancelled, timed out, or otherwise terminal, a delayed result SHALL not change it to success.

#### Scenario: Conditional dispatch loses a reconnect race

- **WHEN** a command is cancelled or its session is replaced before dispatch acknowledgement
- **THEN** the dispatch update affects zero rows or records the race explicitly
- **AND** it does not resurrect the command as active

#### Scenario: Unknown status is rejected

- **WHEN** an API or WebSocket payload contains an unsupported status
- **THEN** the store rejects it or records an invalid/late event
- **AND** no command is marked successful from that payload

### Requirement: Retention removes only old terminal history in batches

Housekeeping SHALL remove events and commands older than 90 days only when they are terminal, SHALL process deletions in bounded batches, and SHALL never delete active commands. Retention SHALL be safe to run repeatedly.

#### Scenario: Old terminal rows are retained until housekeeping

- **WHEN** terminal commands and events exceed the 90-day retention age
- **THEN** a retention batch may remove them and report the number removed
- **AND** rows newer than the cutoff remain available

#### Scenario: Active command is protected

- **WHEN** an active command is older than the retention cutoff
- **THEN** retention skips it
- **AND** its command, deadline, and ownership remain intact

### Requirement: Cursor ordering is stable and indexed

Command and event listings SHALL use a deterministic order based on timestamp and a unique row ID, and SHALL return a cursor that can resume after the last returned row without full-table scans for the agent-scoped path.

#### Scenario: Cursor does not duplicate rows

- **WHEN** new rows are inserted between two page requests
- **THEN** the resumed query returns rows after the prior cursor according to the stable order
- **AND** no previously returned row is repeated
