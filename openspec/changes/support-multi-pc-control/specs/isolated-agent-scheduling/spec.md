## ADDED Requirements

### Requirement: The scheduler owns independent per-agent next runs

The fleet scheduler SHALL maintain an independent `next_run` and `RhythmEngine` state for every registered agent. A delayed or failed schedule decision for one agent MUST NOT advance, block, or overwrite another agent's schedule.

#### Scenario: Independent schedules progress separately

- **WHEN** `agent-a` is in a long pause and `agent-b` reaches its next run
- **THEN** `agent-b` may be evaluated and dispatched without waiting for `agent-a`
- **AND** each agent retains its own next-run value

#### Scenario: Housekeeping runs before schedule gating

- **WHEN** the scheduler tick occurs before any agent's `next_run`
- **THEN** stale-command timeout housekeeping still runs for all agents
- **AND** timeout processing is not skipped because the next routine is scheduled later

### Requirement: Effective execution uses the three required gates

For every candidate command, the scheduler SHALL require the fleet master to be active, the target agent to be enabled, and the current time to be inside that agent's work window. An offline agent SHALL not receive a command.

#### Scenario: Outside the work window

- **WHEN** the fleet is active and an agent is enabled but its local time is before `work_start` or at/after `work_end`
- **THEN** the scheduler does not create or dispatch a new command for that agent
- **AND** any active command belonging to the closing window is cooperatively cancelled

#### Scenario: Offline agent does not block the fleet

- **WHEN** `agent-a` is offline and `agent-b` is online, enabled, and inside its window
- **THEN** `agent-a` is skipped without a command
- **AND** `agent-b` remains eligible for its own command

### Requirement: Work windows are explicit, local, and same-day in v1

Each agent SHALL have `work_start`, `work_end`, and an IANA `timezone`. Defaults SHALL be `08:30`, `18:30`, and `America/Sao_Paulo`. The first version SHALL reject windows that cross midnight and SHALL evaluate boundaries with aware datetimes using `ZoneInfo`.

#### Scenario: Default schedule is applied to a new agent

- **WHEN** a new agent is onboarded without schedule overrides
- **THEN** its effective window is 08:30 through 18:30 in `America/Sao_Paulo`
- **AND** the profile does not replace those explicit values

#### Scenario: Different timezones are isolated

- **WHEN** two enabled agents have the same UTC instant but different valid IANA timezones
- **THEN** each agent is evaluated against its own local window
- **AND** changing one timezone does not alter the other agent's next run

#### Scenario: Cross-midnight window is rejected

- **WHEN** a settings update sets `work_end` at or before `work_start` for a same-day schedule
- **THEN** validation rejects the update
- **AND** the previous valid window remains active

### Requirement: Profile changes rhythm but not the workday

The scheduler SHALL continue to use the configured profile for energy, pauses, and routine multipliers, but SHALL use `work_start` and `work_end` as the sole workday boundaries. A change to settings, work window, or timezone SHALL reset the selected agent's rhythm plan and next-run calculation.

#### Scenario: Profile does not move explicit boundaries

- **WHEN** an agent changes from one valid profile to another while keeping the same work window
- **THEN** rhythm behavior may change
- **AND** the start and end of eligibility remain the configured `work_start` and `work_end`

#### Scenario: Settings revision resets only one rhythm engine

- **WHEN** `agent-a` settings revision changes while `agent-b` remains unchanged
- **THEN** `agent-a`'s day plan, rhythm state, and next run are recalculated
- **AND** `agent-b`'s rhythm state and next run are preserved

### Requirement: One active command is enforced per agent

The scheduler SHALL not create or dispatch a second active command for an agent while its first command is queued, dispatched, running, or awaiting terminal cleanup. This restriction SHALL be scoped by `agent_id`.

#### Scenario: Same PC is busy

- **WHEN** `agent-a` has an active command and reaches another schedule tick
- **THEN** no second command is created for `agent-a`
- **AND** the scheduler continues housekeeping and evaluates other eligible agents

#### Scenario: Other PC is not blocked

- **WHEN** `agent-a` is busy and `agent-b` has no active command
- **THEN** `agent-b` may receive a command when its own `next_run` and gates allow it

### Requirement: Command deadlines are estimated, bounded, and per-command

The hub SHALL estimate command duration from the command payload, set an execution budget to `ceil(estimate * 1.5 + 15 seconds)`, and set the hub deadline 10 seconds after that budget. The worst-case deadline for accepted settings SHALL not exceed 1,800 seconds. Timeout housekeeping SHALL use each command's stored deadline rather than one global timeout.

#### Scenario: Routine gets a calculated deadline

- **WHEN** the scheduler creates a command with a known payload estimate
- **THEN** the command stores its own execution budget and `deadline_at`
- **AND** timeout handling uses those values even if another command has a different estimate

#### Scenario: Unsafe settings are rejected

- **WHEN** a settings payload could produce a routine whose calculated worst-case deadline exceeds 1,800 seconds
- **THEN** the settings update is rejected before it can be scheduled
- **AND** the prior valid settings remain active

### Requirement: Gate changes cancel cooperatively and log transitions only

The scheduler SHALL cancel eligible active commands when the fleet is paused, an agent is disabled, or its work window closes. Connectivity and scheduler blocking events SHALL be recorded on state transitions rather than once per tick while the state is unchanged.

#### Scenario: Window closes during an active command

- **WHEN** the local time reaches `work_end` for an agent with a running command
- **THEN** the hub requests cancellation for that agent's session
- **AND** the command reaches a cancellation/timeout terminal state without being converted to success by a late result

#### Scenario: Offline transition is deduplicated

- **WHEN** an agent remains offline across many scheduler ticks
- **THEN** the hub records one offline/blocking transition for that period
- **AND** it does not emit a repeated skip event on every tick
- **AND** a later reconnect may record one transition back to online
