## Context

The mouse click routine currently stores fixed coordinates in hub settings and sends those coordinates to the Windows agent. A default `(0, 0)` target is unsafe because it is a PyAutoGUI fail-safe corner. The VS Code routine currently types arbitrary random characters with a hardcoded `0.03` second character interval.

## Goals / Non-Goals

**Goals:**
- Randomize mouse click positions inside the Windows agent using the current screen size.
- Keep the PyAutoGUI fail-safe enabled and avoid generated corner/edge targets.
- Make VS Code typing speed configurable from the hub UI.
- Generate Go-like code snippets instead of arbitrary random text.

**Non-Goals:**
- No image recognition or target detection.
- No disabling PyAutoGUI fail-safe.
- No full Go parser or formatter dependency.

## Decisions

- The hub will send `margin`, `button`, and `clicks` for `mouse_click`; the agent will choose `x/y` at execution time because only the agent knows the active screen size.
- The hub will keep accepting legacy `mouse_click_x/y` settings for compatibility but the UI and command payload will no longer rely on fixed coordinates.
- The new `mouse_click_margin` setting defaults to `100` pixels and is validated by the hub. The agent clamps the margin to fit small screens.
- The new `vscode_typing_interval_seconds` setting defaults to `0.08` seconds and is validated between `0` and `2` seconds.
- Go code generation will use built-in templates with randomized identifiers and values. The existing `vscode_text_length` remains the approximate size control.

## Risks / Trade-offs

- [Random clicks can still hit unwanted UI] -> Keep automation paused by default, keep click routine opt-in, and avoid edges/corners through the margin.
- [Small screens may not support a large margin] -> Clamp the effective margin inside the agent before choosing a point.
- [Generated Go code may not compile as a full program every time] -> Generate plausible snippets with package/function structure, not arbitrary keyboard noise.
