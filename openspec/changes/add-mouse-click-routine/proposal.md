## Why

Operators can already configure app-opening and typing routines, but there is no allowlisted way to include simple mouse activity in the same scheduler. Adding a controlled click routine lets the hub perform authorized, explicit mouse clicks without opening arbitrary command execution.

## What Changes

- Add a configurable mouse click routine to the hub settings and web UI.
- Validate click coordinates, button, and click count before settings are persisted.
- Extend scheduler command creation to send mouse click parameters to the Windows agent.
- Extend the Windows agent allowlist with a dry-run aware mouse click command.
- Document the Windows-session requirement and safety constraints for click automation.

## Capabilities

### New Capabilities
- `mouse-click-routine`: Covers configuring, scheduling, and executing allowlisted mouse clicks through the hub and Windows agent.

### Modified Capabilities
None.

## Impact

- Affected code: `hub/control_hub/domain.py`, `hub/control_hub/static/*`, `windows_agent/agent.py`.
- Affected tests: hub domain validation tests and agent dispatcher dry-run tests.
- Affected docs: Windows agent setup guidance and root safety boundaries.
