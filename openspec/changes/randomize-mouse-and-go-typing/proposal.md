## Why

Fixed mouse coordinates are too brittle and can hit PyAutoGUI fail-safe corners when left at defaults. VS Code typing also looks more realistic and safer when it emits plausible Go code at a configurable slower pace instead of arbitrary characters.

## What Changes

- Change mouse click dispatch from fixed coordinates to random safe screen positions selected by the Windows agent.
- Add a configurable mouse click safe margin so random points avoid screen corners and edges.
- Add a configurable VS Code typing interval between characters.
- Replace random character typing with generated Go snippets sized approximately by the existing text length setting.
- Update web UI labels, validation, docs, and tests for the new behavior.

## Capabilities

### New Capabilities
- `randomized-activity-routines`: Covers random mouse click targeting and Go code typing controls for the existing routine scheduler.

### Modified Capabilities
None.

## Impact

- Affected hub code: `hub/control_hub/domain.py`, `hub/control_hub/static/*`, `hub/control_hub/store.py`.
- Affected agent code: `windows_agent/agent.py`.
- Affected tests: hub domain validation and agent dispatcher tests.
- Affected docs: Windows agent setup guidance.
