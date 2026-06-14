## ADDED Requirements

### Requirement: Containerized hub runtime
The project SHALL provide a Docker Compose runtime for the hub on Ubuntu Server.

#### Scenario: Hub starts from Compose
- **WHEN** an operator runs Docker Compose with required environment variables
- **THEN** the hub starts, exposes the configured local HTTP port, and stores data in a persistent volume

### Requirement: Environment based configuration
The hub SHALL load operational settings from environment variables and local persisted configuration.

#### Scenario: Pairing token is configured
- **WHEN** `CONTROL_PAIRING_TOKEN` is provided to the container
- **THEN** the hub uses it to authenticate Windows agent connections

### Requirement: Windows agent setup documentation
The project SHALL document how to install and run the Windows agent on the authorized Windows machine.

#### Scenario: Operator follows agent setup
- **WHEN** an operator follows the Windows setup documentation
- **THEN** the agent can connect to the hub using the pairing token and report heartbeat

### Requirement: Health checks
The hub SHALL expose a health endpoint suitable for Docker and server validation.

#### Scenario: Health endpoint is called
- **WHEN** an operator or container health check calls the health endpoint
- **THEN** the hub returns a successful status if the API process is running
