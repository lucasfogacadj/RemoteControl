## ADDED Requirements

### Requirement: Configurable mouse click routine
The system SHALL allow an operator to configure a mouse click routine with absolute screen coordinates, button, click count, enabled state, and dispatch percentage.

#### Scenario: Operator saves valid click settings
- **WHEN** an operator saves mouse click settings with non-negative coordinates, a supported button, click count within the allowed range, and enabled routine percentages totaling 100
- **THEN** the hub persists the settings and includes the mouse click routine in routine selection

#### Scenario: Operator saves invalid click settings
- **WHEN** an operator saves mouse click settings with invalid coordinates, unsupported button, invalid click count, or enabled routine percentages that do not total 100
- **THEN** the hub rejects the configuration and explains the validation error

### Requirement: Mouse click command dispatch
The scheduler SHALL build mouse click commands only from validated settings and SHALL include the configured coordinates, button, and click count in the command payload.

#### Scenario: Mouse click routine is selected
- **WHEN** global automation is enabled, an agent is connected, and the weighted scheduler selects the mouse click routine
- **THEN** the hub dispatches a `mouse_click` command containing the configured click parameters and records the command lifecycle

### Requirement: Allowlisted mouse click execution
The Windows agent SHALL execute `mouse_click` commands as an allowlisted command using the configured absolute coordinates, button, and click count.

#### Scenario: Mouse click dry-run
- **WHEN** the agent receives a `mouse_click` command while dry-run mode is enabled
- **THEN** it reports success without moving or clicking the mouse

#### Scenario: Mouse click active execution
- **WHEN** the agent receives a valid `mouse_click` command while dry-run mode is disabled
- **THEN** it performs the configured click with `pyautogui` and reports the result
