## Context

The hub already persists settings as JSON and sends allowlisted commands to the Windows agent over WebSocket. The agent already has cooperative cancellation for sleeps and typing, and the scheduler is resilient to runtime errors. The implementation can therefore extend the existing command contract without schema migration.

## Goals / Non-Goals

**Goals:**
- Make typing cadence non-uniform with configurable typo correction and thinking pauses.
- Support multiple code languages with built-in generators and a random selection mode.
- Move the mouse through human-like paths before clicks and support move-only routines.
- Let the scheduler vary timing and routine choice by workday rhythm, organic pauses, and activity mode.
- Execute contextual scenarios as a single command containing allowlisted sub-actions.
- Keep all new behavior configurable from the hub UI.

**Non-Goals:**
- No image recognition, accessibility tree inspection, or app-specific DOM scraping.
- No arbitrary command execution from the hub.
- No credential collection or automatic credential entry.
- No disabling PyAutoGUI fail-safe.

## Decisions

- New settings remain in the existing settings JSON and are validated by `domain.py`.
- The scheduler owns `RhythmEngine` state in memory. This keeps pause schedules and activity modes lightweight and avoids a database migration.
- `build_command()` accepts optional rhythm context so typing speed and routine selection can be influenced by energy without changing stored percentages.
- Scenario command payloads include explicit sub-actions. The agent executes only known sub-action types: `open_app`, `wait`, `scroll`, `hotkey`, `alt_tab`, `type_text`, `mouse_move`, and `mouse_click`.
- Mouse path generation lives in `windows_agent/mouse_humanizer.py` so geometry can be unit-tested without touching the real desktop.
- Dry-run mode reports intended behavior and does not open apps, move the mouse, scroll, or type.

## Risks / Trade-offs

- [Scenario commands can run longer than atomic commands] -> Keep scenario waits bounded and rely on existing cooperative cancellation and command timeout.
- [Mouse paths still cannot know true UI targets] -> Use weighted interest zones and safe bounds rather than pretending to identify controls.
- [Rhythm state resets on hub restart] -> Acceptable because schedules are organic and regenerated from saved settings.
- [Discord typing could be sensitive] -> Scenario text is typed but not submitted with Enter.
