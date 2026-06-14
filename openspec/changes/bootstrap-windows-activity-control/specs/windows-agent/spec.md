## ADDED Requirements

### Requirement: Authenticated outbound agent connection
The Windows agent SHALL connect outbound to the hub and authenticate with the configured pairing token.

#### Scenario: Agent sends heartbeat
- **WHEN** the agent is running and authenticated
- **THEN** it sends periodic heartbeat messages so the hub can report online status

### Requirement: Allowlisted routine execution
The Windows agent SHALL execute only the supported routine commands received from the hub.

#### Scenario: Unsupported command is rejected
- **WHEN** the agent receives a command whose type is not allowlisted
- **THEN** it refuses the command and reports a failure result to the hub

### Requirement: VS Code random text routine
The Windows agent SHALL open the configured target file in Visual Studio Code and type generated random text only into that file.

#### Scenario: Target file is configured
- **WHEN** the agent receives a VS Code typing command with a configured target file
- **THEN** it opens that file in VS Code and types the requested amount of random text

#### Scenario: Target file is missing
- **WHEN** the agent receives a VS Code typing command without a configured target file
- **THEN** it refuses the command and reports a configuration error

### Requirement: Discord routine
The Windows agent SHALL open or focus Discord using the configured executable or system launcher.

#### Scenario: Discord command executes
- **WHEN** the agent receives an open Discord command
- **THEN** it opens or focuses Discord and reports the result

### Requirement: Gmail routine
The Windows agent SHALL open or focus Chrome at the Gmail URL without handling credentials.

#### Scenario: Gmail command executes
- **WHEN** the agent receives an open Gmail command
- **THEN** it opens Chrome at `https://mail.google.com/` and reports the result

#### Scenario: Gmail requires login
- **WHEN** Chrome opens Gmail and the browser session is not authenticated
- **THEN** the agent does not enter credentials and reports that manual login may be required
