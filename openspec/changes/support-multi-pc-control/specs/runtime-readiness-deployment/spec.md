## ADDED Requirements

### Requirement: Health remains compatible and readiness is dependency-aware

The hub SHALL preserve the existing `/health` response contract. It SHALL expose separate liveness and readiness endpoints that report process, SQLite/migration, scheduler, and watchdog status. An offline agent SHALL not by itself make the hub unready.

#### Scenario: Healthy hub with offline agent

- **WHEN** SQLite, migrations, scheduler, and watchdog are healthy but no Windows agent is connected
- **THEN** `/health` remains successful
- **AND** liveness and readiness remain successful
- **AND** the fleet state reports the agent offline as operational data

#### Scenario: Migration or SQLite is unavailable

- **WHEN** required migration or SQLite integrity/readiness checks fail
- **THEN** readiness fails with a useful dependency status
- **AND** liveness can still indicate that the process is alive if the process itself is responsive

### Requirement: Shutdown closes resources and marks sessions offline

On graceful shutdown, the hub SHALL stop scheduler, watchdog, housekeeping, and polling-related tasks, request cooperative cancellation for active slots within the configured shutdown budget, close SQLite, and persist connected sessions as offline before exit.

#### Scenario: Graceful hub restart

- **WHEN** the hub receives a graceful shutdown signal
- **THEN** it does not leave the SQLite connection open or a scheduler task running
- **AND** the next startup reports previously persisted sessions offline until they reconnect

#### Scenario: Agent offline does not block shutdown indefinitely

- **WHEN** a socket is already broken during shutdown
- **THEN** cleanup is bounded and idempotent
- **AND** the process still closes its database and exits without requiring a live agent

### Requirement: Agent heartbeat and reconnect use bounded variability

The Windows agent SHALL add bounded jitter to heartbeat timing and SHALL use exponential reconnect backoff with a cap and reset after a successful connection. The agent SHALL preserve dry-run behavior and shall not log or expose the pairing token.

#### Scenario: Heartbeats are not synchronized exactly

- **WHEN** multiple agents start with the same heartbeat interval
- **THEN** their heartbeat send times include bounded jitter
- **AND** the configured minimum/maximum safety bounds are respected

#### Scenario: Reconnect backs off and resets

- **WHEN** the agent experiences repeated connection failures
- **THEN** retry delays grow exponentially up to the configured cap
- **AND** after a successful connection the next failure starts from the base delay

### Requirement: Container runtime remains a single-worker deployment

The deployment SHALL exclude `.env` and other local secrets from the Docker build context, configure container restart behavior, and explicitly run one Uvicorn worker so in-memory session ownership is not split across processes.

#### Scenario: Docker configuration is inspected

- **WHEN** `docker compose config` is run against the project
- **THEN** the compose model is valid
- **AND** restart policy, persistent database volume, secret exclusion, and one-worker runtime settings are visible

#### Scenario: Local secret is in the workspace

- **WHEN** a developer has a `.env` file beside the Dockerfile
- **THEN** the build context excludes it
- **AND** the image does not contain the local pairing token

### Requirement: Rollout and rollback are documented as a paused operation

Operational documentation SHALL require pausing the fleet, generating and validating a backup, updating the hub, updating the legacy agent with the explicit migrated ID, validating dry-run and health, and only then reactivating authorized agents. Push, PR, and production deploy SHALL remain explicit operator actions.

#### Scenario: Safe first rollout

- **WHEN** an operator follows the documented rollout
- **THEN** no new command is scheduled during backup/migration/agent update
- **AND** dry-run and per-agent isolation are validated before the master switch is re-enabled

#### Scenario: Rollback after failed validation

- **WHEN** dry-run, migration, or readiness validation fails
- **THEN** the documented procedure keeps the fleet paused and identifies the previous artifact/backup to restore
- **AND** it does not require deleting the legacy structures before the operator decides to roll back
