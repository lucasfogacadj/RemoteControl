## ADDED Requirements

### Requirement: The console presents fleet summary and selected-agent detail

The UI SHALL show a fleet summary, a selectable list of registered PCs, and detail for the selected PC including connectivity, enabled state, settings, active command, and history. A “Pausar todos” control SHALL remain visible regardless of which PC is selected.

#### Scenario: Operator switches between two PCs

- **WHEN** the operator selects `agent-b` after viewing `agent-a`
- **THEN** the detail panel and history reload only `agent-b` data
- **AND** the fleet summary remains available

#### Scenario: Master pause remains reachable

- **WHEN** the selected PC changes or a detail request fails
- **THEN** the master pause control remains visible and operable
- **AND** it is clearly represented as a global action rather than an individual toggle

### Requirement: Selection persists without silently discarding edits

The console SHALL persist the selected `agent_id` in browser storage. When the settings form has unsaved changes, changing the selection or applying a new server snapshot SHALL require an explicit save, discard, or cancel decision.

#### Scenario: Reload restores the selected PC

- **WHEN** the page is reloaded after the operator selected `agent-b`
- **THEN** the console restores `agent-b` if it still exists
- **AND** it falls back visibly and deterministically if the agent was removed or is unavailable

#### Scenario: Dirty form blocks a silent switch

- **WHEN** the operator edits `agent-a` settings and clicks `agent-b` before saving
- **THEN** the UI does not replace the form with `agent-b` data immediately
- **AND** it offers an explicit action to save, discard, or cancel the switch

### Requirement: Dynamic content is rendered safely

The console SHALL render agent IDs, labels, event messages, command messages, and other server-provided values using DOM node creation and `textContent` or an equivalent escaping-safe API. It SHALL not insert untrusted dynamic data through `innerHTML`.

#### Scenario: Event message contains markup

- **WHEN** an event message contains HTML or script-looking text
- **THEN** the console displays it as text
- **AND** no element, handler, or script is created from that content

#### Scenario: Server-controlled label remains bounded

- **WHEN** a response includes a routine label or agent name
- **THEN** the UI displays the value in the intended text node
- **AND** it does not treat the value as markup or executable code

### Requirement: Polling is split, cancellable, and visibility-aware

The console SHALL use a lightweight fleet poll separate from the selected-agent detail/history poll. It SHALL cancel obsolete requests when selection changes, ignore stale responses, and suspend periodic polling while the document is hidden.

#### Scenario: Selection change cancels old detail request

- **WHEN** a detail request for `agent-a` is pending and the operator selects `agent-b`
- **THEN** the `agent-a` request is aborted or its response is ignored
- **AND** the visible detail cannot be overwritten by `agent-a` after the switch

#### Scenario: Hidden page suspends polling

- **WHEN** the browser marks the page hidden
- **THEN** periodic fleet and detail polls stop or are deferred
- **AND** polling resumes with a fresh request when the page becomes visible

### Requirement: Loading, errors, and conflicts are explicit

The UI SHALL expose loading and error states for fleet, detail, settings save, toggle, and cancel operations. A stale revision/`ETag` response SHALL preserve the operator's unsaved input until the operator chooses how to reconcile it.

#### Scenario: Detail API fails

- **WHEN** the selected-agent request returns an error
- **THEN** the detail area shows a recoverable error state with a retry action
- **AND** the fleet summary and master pause action remain usable

#### Scenario: Settings conflict occurs

- **WHEN** the settings API rejects the form because another client changed the revision
- **THEN** the UI tells the operator that the server version is newer
- **AND** it does not silently overwrite the local edits

### Requirement: Interactive controls meet baseline accessibility

The console SHALL expose toggle state through `aria-pressed` or an equivalent accessible state, SHALL retain a visible focus indicator, SHALL provide keyboard-accessible controls, and SHALL use interaction targets of at least 44 CSS pixels where applicable.

#### Scenario: Keyboard operator pauses a PC

- **WHEN** the operator focuses the individual toggle using the keyboard
- **THEN** focus is visibly indicated
- **AND** activating the control updates its accessible pressed state and status text

#### Scenario: Responsive layouts preserve core actions

- **WHEN** the console is rendered at 375 px, 768 px, and desktop widths
- **THEN** PC selection, selected detail, individual cancel/toggle, settings save, and master pause remain reachable without horizontal clipping
