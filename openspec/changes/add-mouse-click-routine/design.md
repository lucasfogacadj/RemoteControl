## Context

The hub currently stores a fixed set of routine definitions, validates their percentages, and builds allowlisted commands for the Windows agent. The agent currently accepts only VS Code typing, Discord, and Gmail commands. Mouse clicks need to fit this same model so they remain explicit, configurable, dry-run safe, and auditable.

## Goals / Non-Goals

**Goals:**
- Add one allowlisted mouse click routine with configurable absolute screen coordinates.
- Keep validation in the hub so invalid coordinates, buttons, or click counts are rejected before dispatch.
- Keep the agent dispatcher closed by default and dry-run aware.
- Expose the click settings in the existing local web console without adding a separate workflow.

**Non-Goals:**
- No arbitrary script execution or general-purpose remote desktop control.
- No screen discovery, image recognition, drag operations, or credential handling.
- No automatic focusing of an application before the click; the operator is responsible for choosing coordinates that are safe for the visible Windows session.

## Decisions

- Model mouse clicks as a normal weighted routine (`mouse_click`) instead of a manual one-off command. This keeps scheduling, auditing, enable/disable behavior, and percentage validation consistent with the existing routines.
- Store click parameters at settings level (`mouse_click_x`, `mouse_click_y`, `mouse_click_button`, `mouse_click_count`). This avoids creating a nested per-routine schema while the existing UI and backend still treat routines as weighted entries.
- Validate coordinates as non-negative integers and click count as a small bounded integer. Absolute clicks are powerful, so bad values should fail early in `/api/settings` and `/api/toggle`.
- Use `pyautogui.click(x=..., y=..., button=..., clicks=...)` in the agent. The dependency is already required for VS Code typing, so no new runtime package is needed.

## Risks / Trade-offs

- [Wrong coordinates can click the wrong target] -> Require explicit coordinates in the hub, document that the Windows session must be visible and authorized, and keep dry-run as the default agent mode.
- [Different monitor layouts change coordinate meaning] -> Treat coordinates as absolute screen coordinates owned by the operator; do not attempt automatic remapping in this change.
- [Click automation expands GUI control surface] -> Keep it as a single allowlisted command with strict parameter validation and no arbitrary command execution.
