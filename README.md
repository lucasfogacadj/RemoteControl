# Windows Activity Control

Hub local containerizado para orquestrar rotinas autorizadas em um computador Windows com agente local explicito.

## Arquitetura

- `hub/`: API FastAPI, UI web local, scheduler, persistencia SQLite e WebSocket para o agente.
- `windows_agent/`: agente Python para rodar na sessao interativa do Windows autorizado.
- `docs/`: guias de deploy no Ubuntu Server e configuracao do agente Windows.
- `scripts/` e `ops/systemd/`: deploy automatico no servidor.
- `openspec/`: proposta, specs, design e tarefas do OpenSpec.

O Ubuntu Server executa o hub em container. O Windows executa o agente localmente, conectado de saida ao hub por WebSocket com token compartilhado.

AnyDesk fica apenas como canal manual de acesso/suporte. O projeto nao automatiza a janela do AnyDesk e nao envia scripts arbitrarios ao Windows.

## Limites de seguranca

- Use somente em maquinas suas ou com autorizacao explicita.
- O agente executa apenas comandos allowlisted: VS Code, Discord e Chrome/Gmail.
- A digitacao aleatoria e restrita ao arquivo configurado para o VS Code.
- O sistema nao coleta, armazena ou preenche credenciais.
- Rotinas de GUI exigem sessao Windows interativa ativa.

## Inicio rapido do hub

1. Copie `.env.example` para `.env` e troque `CONTROL_PAIRING_TOKEN`.
2. Suba o hub:

```powershell
docker compose up --build
```

3. Abra `http://localhost:8080`.

## Inicio rapido do agente Windows

Veja [docs/windows-agent.md](docs/windows-agent.md).

## Deploy automatico

Veja [docs/autodeploy.md](docs/autodeploy.md) e [docs/ubuntu-server.md](docs/ubuntu-server.md).

Em modo dry-run, o agente conecta e responde comandos sem abrir programas:

```powershell
cd D:\Projetos\control
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r windows_agent\requirements.txt
$env:CONTROL_HUB_WS_URL="ws://localhost:8080/ws/agent"
$env:CONTROL_PAIRING_TOKEN="change-this-token"
$env:CONTROL_AGENT_DRY_RUN="true"
python -m windows_agent.agent
```

## OpenSpec

A mudanca inicial esta em `openspec/changes/bootstrap-windows-activity-control/`.

Comandos uteis:

```powershell
npx -y @fission-ai/openspec@latest validate bootstrap-windows-activity-control
npx -y @fission-ai/openspec@latest status --change bootstrap-windows-activity-control
```
