## 1. Project Skeleton

- [x] 1.1 Create repository structure for hub, Windows agent, docs, tests, and Docker assets
- [x] 1.2 Add root README with architecture, safety boundaries, and quick start
- [x] 1.3 Add environment examples for hub and agent without committing secrets

## 2. Hub Backend

- [x] 2.1 Implement FastAPI app with health endpoint and static UI serving
- [x] 2.2 Implement SQLite persistence for settings, agent state, commands, and events
- [x] 2.3 Implement REST endpoints for reading state, saving settings, toggling automation, and listing events
- [x] 2.4 Implement WebSocket endpoint with pairing token authentication for Windows agents
- [x] 2.5 Implement command result handling and event recording

## 3. Scheduler

- [x] 3.1 Implement global activation gate and interval loop
- [x] 3.2 Implement percentage validation and weighted routine selection
- [x] 3.3 Implement command creation for VS Code typing, Discord, and Gmail routines
- [x] 3.4 Implement pending command cancellation when automation is disabled

## 4. Web Interface

- [x] 4.1 Build local dashboard showing enabled state, agent heartbeat, routine percentages, and recent events
- [x] 4.2 Build controls to save routine settings and toggle automation
- [x] 4.3 Show validation errors and connection state clearly

## 5. Windows Agent

- [x] 5.1 Implement agent configuration loading from environment variables
- [x] 5.2 Implement authenticated outbound WebSocket connection and heartbeat
- [x] 5.3 Implement allowlisted command dispatcher with dry-run support
- [x] 5.4 Implement VS Code target file typing routine
- [x] 5.5 Implement Discord open/focus routine
- [x] 5.6 Implement Chrome Gmail routine without credential handling

## 6. Deployment and Documentation

- [x] 6.1 Add Dockerfile and Docker Compose for Ubuntu Server hub runtime
- [x] 6.2 Add Windows agent setup documentation
- [x] 6.3 Add Ubuntu Server deployment documentation

## 7. Verification

- [x] 7.1 Add backend unit tests for settings validation and weighted selection
- [x] 7.2 Add agent dry-run tests for allowlisted command handling
- [x] 7.3 Run OpenSpec validation and project tests
