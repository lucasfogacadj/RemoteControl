## Why

The existing activity routines used flat random timing, Go-only content, direct mouse clicks, and independent routine selection. That made the generated GUI activity too mechanical and left no contract for richer human-like timing, mouse paths, day rhythm, or contextual action sequences.

## What Changes

- Add humanized typing parameters for typo correction, thinking pauses, and code language selection.
- Generate code in Go, Python, JavaScript, TypeScript, Rust, Java, or random language mode.
- Replace direct mouse clicking with Bezier mouse paths, weighted screen zones, drift, hesitation, and overshoot.
- Add a mouse movement routine that moves without clicking.
- Add a rhythm engine for energy, organic pauses, work profiles, and activity clustering.
- Add scenario commands for contextual coding, email, and Discord sequences.
- Add scroll, hotkey, and Alt+Tab sub-actions in the Windows agent.
- Expose the new controls in the web UI and document the runtime behavior.

## Capabilities

### New Capabilities
- `humanized-activity-simulation`: Covers humanized typing, natural mouse movement, rhythm-aware scheduling, scenario execution, scroll, hotkeys, and Alt+Tab behavior.

### Modified Capabilities
- `randomized-activity-routines`: Extends the prior random mouse and Go typing behavior into a broader humanization model.

## Impact

- Affected hub code: `hub/control_hub/domain.py`, `hub/control_hub/scheduler.py`, `hub/control_hub/rhythm.py`, `hub/control_hub/scenarios.py`, `hub/control_hub/static/*`.
- Affected agent code: `windows_agent/agent.py`, `windows_agent/mouse_humanizer.py`.
- Affected tests: hub domain, scheduler, rhythm, mouse humanizer, and agent dispatcher tests.
- Affected docs: README and Windows agent setup guide.
