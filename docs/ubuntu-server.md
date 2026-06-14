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
```

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

