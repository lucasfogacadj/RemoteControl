# Windows Activity Control

Hub local containerizado para orquestrar rotinas autorizadas em um computador Windows com agente local explicito.

## Arquitetura

- `hub/`: API FastAPI, UI web local, scheduler, persistencia SQLite e WebSocket para o agente.
- `windows_agent/`: agente Python para rodar na sessao interativa do Windows autorizado.
- `docs/`: guias de deploy no Ubuntu Server e configuracao do agente Windows.
- `scripts/` e `ops/systemd/`: deploy automatico no servidor.
- `openspec/`: proposta, specs, design e tarefas do OpenSpec.

O Ubuntu Server executa o hub em container. O Windows executa o agente localmente, conectado de saida ao hub por WebSocket com token compartilhado.

O hub suporta uma frota pequena de ate 10 PCs em uma unica instancia Uvicorn/SQLite. Cada PC possui configuracao, jornada, fuso, historico e comando ativo independentes. A regra de execucao e sempre: **frota ativa AND PC ativo AND dentro da janela de trabalho**.

AnyDesk fica apenas como canal manual de acesso/suporte. O projeto nao automatiza a janela do AnyDesk e nao envia scripts arbitrarios ao Windows.

## Limites de seguranca

- Use somente em maquinas suas ou com autorizacao explicita.
- O agente executa apenas comandos allowlisted: VS Code, Discord, Chrome/Gmail, movimento/click de mouse e cenarios compostos definidos pelo hub.
- A digitacao aleatoria e restrita ao arquivo configurado para o VS Code.
- A digitacao do VS Code usa geradores de codigo allowlisted, com linguagem, taxa de erro, pausas e intervalo entre teclas configurados no hub.
- Movimentos e clicks de mouse usam zonas de interesse, trajetorias curvas e margem segura configurada no hub, e dependem da sessao Windows visivel.
- O scheduler aplica ritmo diario configuravel, incluindo perfil, almoco, coffee breaks, micro-pausas e cenarios de trabalho.
- O sistema nao coleta, armazena ou preenche credenciais.
- Rotinas de GUI exigem sessao Windows interativa ativa.
- A UI/API nao possuem login de operador nesta versao. Mantenha a porta somente em rede confiavel ou VPN e proteja o token compartilhado.

## Inicio rapido do hub

1. Copie `.env.example` para `.env` e troque `CONTROL_PAIRING_TOKEN`.
   Para habilitar Sentry, preencha `CONTROL_SENTRY_DSN` com o DSN do projeto e ajuste `CONTROL_SENTRY_ENVIRONMENT`/`CONTROL_SENTRY_RELEASE` se desejar.
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
$env:CONTROL_AGENT_ID="windows-desktop-01"
$env:CONTROL_AGENT_DRY_RUN="true"
$env:CONTROL_SENTRY_DSN="https://..."
python -m windows_agent.agent
```

## Operacao multi-PC e rollout

Novos agentes com `CONTROL_AGENT_ID` valido sao cadastrados automaticamente, mas nascem desativados. Ative cada PC pela console somente depois de validar dry-run. O botao **Pausar todos** e o endpoint `POST /api/toggle` continuam sendo o kill switch global.

No primeiro rollout multi-PC, pause a frota, gere/valide o backup SQLite, atualize o hub, atualize o agente legado com `CONTROL_AGENT_ID=windows-desktop-01`, valide `dry-run`, `/health` e `/health/ready`, e so entao reative os PCs autorizados. O hub preserva estruturas legadas na primeira versao; nao faca push, PR ou deploy de producao automaticamente.

O registro dos checks locais, browser e Docker esta em [docs/multi-pc-validation.md](docs/multi-pc-validation.md).

Para repetir a validação browser automatizada:

```powershell
npm install
npm run test:e2e
```

## OpenSpec

A mudanca inicial esta em `openspec/changes/bootstrap-windows-activity-control/`.

Comandos uteis:

```powershell
npx -y @fission-ai/openspec@latest validate bootstrap-windows-activity-control
npx -y @fission-ai/openspec@latest status --change bootstrap-windows-activity-control
```
