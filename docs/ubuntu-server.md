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
CONTROL_SENTRY_DSN=https://...
CONTROL_SENTRY_ENVIRONMENT=production
CONTROL_SENTRY_TRACES_SAMPLE_RATE=0
CONTROL_SENTRY_SEND_DEFAULT_PII=false
```

`CONTROL_AGENT_HEARTBEAT_TIMEOUT_SECONDS` define depois de quantos segundos sem heartbeat o hub marca o agente como offline e limpa a conexao antiga. Mantenha esse valor maior que o `CONTROL_AGENT_HEARTBEAT_SECONDS` usado no Windows.

Com `CONTROL_SENTRY_DSN` preenchido, o hub inicializa o SDK do Sentry antes do FastAPI e captura erros HTTP/WebSocket. PII fica desligado por padrao, e campos sensiveis como `token`, `Authorization` e cookies sao filtrados antes do envio.

## Subir

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
```

A UI ficara disponivel em:

```text
http://SEU_UBUNTU_SERVER:8080
```

Se quiser acesso apenas local/VPN, limite firewall e bind/reverso conforme sua rede.

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
