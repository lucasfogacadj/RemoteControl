## ADDED Requirements

### Requirement: Global activation gate
The scheduler SHALL dispatch routine commands only while global automation is enabled.

#### Scenario: Automation disabled
- **WHEN** global automation is disabled
- **THEN** the scheduler does not dispatch any routine command

### Requirement: Weighted routine selection
The scheduler SHALL select enabled routines according to their configured percentages.

#### Scenario: Percentages define eligible routines
- **WHEN** VS Code is 50%, Discord is 25%, and Gmail is 25%
- **THEN** the scheduler selects among those routines using those relative percentages over repeated dispatches

### Requirement: Interval and jitter controls
The scheduler SHALL respect configured minimum and maximum intervals between routine dispatches.

#### Scenario: Next run is scheduled
- **WHEN** a routine command completes
- **THEN** the scheduler calculates the next dispatch time within the configured interval range

### Requirement: Command lifecycle tracking
The scheduler SHALL track each dispatched command until success, failure, timeout, or cancellation.

#### Scenario: Agent reports command failure
- **WHEN** an agent reports command failure
- **THEN** the scheduler records the failure and keeps future scheduling governed by the current configuration

#### Scenario: Automation is disabled while command is pending
- **WHEN** automation is disabled while a command is pending
- **THEN** the scheduler cancels pending undispatched commands and does not create new ones
