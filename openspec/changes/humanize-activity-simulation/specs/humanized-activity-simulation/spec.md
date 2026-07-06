## ADDED Requirements

### Requirement: Humanized typing
The Windows agent SHALL type VS Code content with non-uniform timing, configurable typo correction, thinking pauses, and selectable code language.

#### Scenario: VS Code command includes humanized parameters
- **WHEN** the scheduler builds a VS Code typing command
- **THEN** the command payload includes target file, text length, typing interval, typo rate, thinking pause chance, and code language

#### Scenario: Agent types with corrections
- **WHEN** typo correction is enabled for typed content
- **THEN** the agent may type wrong characters, pause, send backspace corrections, and type the intended character

#### Scenario: Agent generates multiple languages
- **WHEN** the code language is set to `go`, `python`, `js`, `typescript`, `rust`, `java`, or `random`
- **THEN** the agent generates code content for the selected language or randomly chooses one supported language

### Requirement: Natural mouse movement
The Windows agent SHALL move the mouse through safe, human-like paths before mouse clicks and SHALL support move-only commands.

#### Scenario: Mouse click command is built
- **WHEN** the scheduler selects the mouse click routine
- **THEN** the command payload includes button, click count, margin, movement duration, and overshoot chance

#### Scenario: Agent executes mouse click
- **WHEN** the agent receives a mouse click command while dry-run mode is disabled
- **THEN** it chooses a safe interest-zone target, moves with a Bezier path, hesitates briefly, and clicks the target

#### Scenario: Agent executes mouse move
- **WHEN** the agent receives a mouse move command while dry-run mode is disabled
- **THEN** it moves to a safe interest-zone target without clicking

### Requirement: Rhythm-aware scheduling
The scheduler SHALL vary routine selection and dispatch interval by a workday rhythm model and SHALL skip dispatch during organic pauses.

#### Scenario: Scheduler enters organic pause
- **WHEN** the rhythm engine reports lunch, coffee break, micro-break, or long pause
- **THEN** the scheduler records a pause event and does not send a new command

#### Scenario: Scheduler dispatches during active work
- **WHEN** automation is enabled, an agent is connected, no command is active, and rhythm is not paused
- **THEN** the scheduler chooses a routine using rhythm multipliers and schedules the next run using rhythm-adjusted timing

### Requirement: Contextual scenarios
The system SHALL support scenario routines that execute contextual sequences of allowlisted sub-actions.

#### Scenario: Scenario command is built
- **WHEN** the scheduler selects the scenario routine
- **THEN** the command payload includes a scenario type and ordered sub-actions

#### Scenario: Agent executes scenario
- **WHEN** the agent receives a scenario command
- **THEN** it executes only supported sub-actions: app open/focus, wait, scroll, hotkey, Alt+Tab, typed text, mouse move, and mouse click

### Requirement: Scroll, hotkeys, and window transitions
The Windows agent SHALL support scroll bursts, contextual keyboard shortcuts, and realistic Alt+Tab transitions inside scenarios.

#### Scenario: Scenario includes reading behavior
- **WHEN** a scenario includes a scroll sub-action
- **THEN** the agent scrolls in multiple flicks with short read pauses

#### Scenario: Scenario includes hotkeys
- **WHEN** a scenario includes hotkey or Alt+Tab sub-actions
- **THEN** the agent sends the requested keys with bounded pauses between actions
