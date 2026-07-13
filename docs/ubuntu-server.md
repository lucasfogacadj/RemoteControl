# Ubuntu Server Deployment

O Ubuntu Server executa somente o hub: API, UI, scheduler, SQLite e WebSocket do agente. O agente Windows roda fora do container, na propria maquina Windows autorizada.

## Requisitos

- Docker Engine e Docker Compose plugin.
- Porta local escolhida para a UI, padrao `8080`.
- Rede entre Windows e Ubuntu Server.

## Configurar

No servidor:

```bash
git clone <seu-repositorio> control
cd control
cp .env.example .env
nano .env
```

Troque o token:

```bash
CONTROL_PAIRING_TOKEN=um-token-longo-e-privado
CONTROL_PORT=8080
CONTROL_AGENT_HEARTBEAT_TIMEOUT_SECONDS=45
CONTROL_COMMAND_TIMEOUT_SECONDS=120
CONTROL_SHUTDOWN_TIMEOUT_SECONDS=10
CONTROL_SENTRY_DSN=https://...
CONTROL_SENTRY_ENVIRONMENT=production
CONTROL_SENTRY_TRACES_SAMPLE_RATE=0
CONTROL_SENTRY_SEND_DEFAULT_PII=false
```

`CONTROL_AGENT_HEARTBEAT_TIMEOUT_SECONDS` define depois de quantos segundos sem heartbeat o hub marca o agente como offline e limpa a conexao antiga. Mantenha esse valor maior que o `CONTROL_AGENT_HEARTBEAT_SECONDS` usado no Windows. `CONTROL_SHUTDOWN_TIMEOUT_SECONDS` limita a espera do hub pelo cancelamento cooperativo dos slots ativos durante shutdown.

Com `CONTROL_SENTRY_DSN` preenchido, o hub inicializa o SDK do Sentry antes do FastAPI e captura erros HTTP/WebSocket. PII fica desligado por padrao, e campos sensiveis como `token`, `Authorization` e cookies sao filtrados antes do envio.

## Subir

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/health/ready
```

A UI ficara disponivel em:

```text
http://SEU_UBUNTU_SERVER:8080
```

Se quiser acesso apenas local/VPN, limite firewall e bind/reverso conforme sua rede.

## Primeiro rollout multi-PC

1. Na console, use **Pausar todos** e confirme que nao ha comando ativo.
2. Gere um backup SQLite pelo procedimento operacional do hub e confirme `integrity_check`.
3. Atualize o container; a primeira inicializacao cria a migracao multi-PC e preserva dados legados.
4. Atualize o agente existente com `CONTROL_AGENT_ID=windows-desktop-01` e mantenha `CONTROL_AGENT_DRY_RUN=true`.
5. Valide `/health`, `/health/ready`, o estado da frota e um comando/cancelamento em dry-run.
6. Ative somente os PCs autorizados e, por ultimo, a frota.

Para rollback, mantenha a frota pausada, retorne ao artefato anterior e restaure o backup apenas se necessario. Nao exponha a UI/API fora de uma rede confiavel ou VPN: o modelo atual usa token compartilhado e nao possui login de operador.

## Atualizar

```bash
git pull
docker compose up -d --build
```

## Parar

```bash
docker compose down
```

Para apagar tambem os dados locais:

```bash
docker compose down -v
```
