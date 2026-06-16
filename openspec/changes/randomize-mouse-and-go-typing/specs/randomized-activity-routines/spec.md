## ADDED Requirements

### Requirement: Random safe mouse click targets
The system SHALL dispatch mouse click commands without fixed coordinates and the Windows agent SHALL choose a random target within the visible screen while avoiding fail-safe corners and edges.

#### Scenario: Mouse click command is built
- **WHEN** the scheduler selects the mouse click routine
- **THEN** the command payload includes button, click count, and safe margin, but not fixed `x` or `y` coordinates

#### Scenario: Agent executes random click
- **WHEN** the agent receives a mouse click command while dry-run mode is disabled
- **THEN** it chooses a random point inside the screen bounds using the configured margin and clicks there

### Requirement: Configurable Go typing speed
The system SHALL let operators configure the interval between typed characters for the VS Code routine.

#### Scenario: Typing interval is saved
- **WHEN** an operator saves a valid typing interval
- **THEN** the hub persists it and includes it in VS Code typing commands

#### Scenario: Typing interval is invalid
- **WHEN** an operator saves a negative typing interval or a typing interval greater than the allowed maximum
- **THEN** the hub rejects the configuration and explains the validation error

### Requirement: Go code typing content
The Windows agent SHALL type generated Go code snippets for the VS Code routine instead of arbitrary random characters.

#### Scenario: VS Code command executes
- **WHEN** the agent receives a VS Code typing command
- **THEN** it generates Go code sized approximately by the configured text length and types it with the configured interval
