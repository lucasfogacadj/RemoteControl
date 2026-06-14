## ADDED Requirements

### Requirement: Local web console
The system SHALL provide a local web interface for viewing agent status, enabling or disabling automation, editing routine percentages, and inspecting recent activity.

#### Scenario: Dashboard loads current state
- **WHEN** an operator opens the local web interface
- **THEN** the interface displays global enabled state, routine percentages, agent online state, last heartbeat, and recent events

#### Scenario: Operator toggles automation
- **WHEN** an operator turns automation on or off from the web interface
- **THEN** the hub persists the new global enabled state and the scheduler honors it before dispatching any further command

### Requirement: Routine configuration persistence
The system SHALL persist routine configuration locally so settings survive container restarts.

#### Scenario: Configuration survives restart
- **WHEN** an operator saves routine settings and the hub container restarts
- **THEN** the hub reloads the saved settings without requiring reconfiguration

#### Scenario: Percentages are validated
- **WHEN** an operator saves enabled routine percentages whose total is not 100
- **THEN** the hub rejects the configuration and explains the validation error

### Requirement: Agent pairing token
The system SHALL require a shared pairing token before accepting heartbeat or command results from a Windows agent.

#### Scenario: Agent uses valid token
- **WHEN** a Windows agent connects with the configured token
- **THEN** the hub accepts the connection and marks the agent online after heartbeat

#### Scenario: Agent uses invalid token
- **WHEN** a Windows agent connects with a missing or invalid token
- **THEN** the hub rejects the connection and records no executable command for that agent

### Requirement: Audit events
The system SHALL record configuration changes, command dispatches, command results, and agent connectivity events.

#### Scenario: Command result is recorded
- **WHEN** an agent reports success or failure for a routine command
- **THEN** the hub stores an event with timestamp, routine name, result status, and message
