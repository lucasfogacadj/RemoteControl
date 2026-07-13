# Validação multi-PC

## Ambiente validado

- Python: suíte local do projeto.
- Hub E2E: Uvicorn em `127.0.0.1:8768` com SQLite isolado em `output/playwright/`.
- Console: Playwright Test em 375 px, 768 px e 1440 px; traces, screenshots e relatório em `output/playwright/`.
- Container: projeto Compose isolado `control-multi-pc-validation`, publicado temporariamente em `127.0.0.1:8769`.

## Comandos executados

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q hub windows_agent tests
node --check hub\control_hub\static\app.js
npm run test:e2e
npx -y @fission-ai/openspec@latest validate support-multi-pc-control --strict
docker compose config --quiet
docker compose -p control-multi-pc-validation build
docker compose -p control-multi-pc-validation up -d
```

Resultado na última validação local: 97 testes Python e 9 testes browser passaram. A suíte cobre migração/backup, settings estritos, ETag, dois a dez agentes, isolamento de sessão/resultado/cancelamento, sessão substituída, shutdown cooperativo, timeout a cada tick, retenção e carga de heartbeat concorrente. Os testes de scheduler usam um relógio injetável e fixo, mantendo a regra real de jornada sem depender do horário em que a suíte é executada.

No browser, a troca de PC com formulário sujo foi validada com dois agentes: `Cancelar` preserva a edição, `Descartar` troca sem persistir e o conflito ETag mantém a edição sem sobrescrever a revisão externa. A suíte também cobre XSS, erro/retry, polling oculto, master pause, toggle/cancel e ausência de overflow nos três breakpoints.

## Validação do container

O build e a subida reais passaram no Docker Desktop. A validação confirmou:

- `/health/ready` saudável antes e depois de `docker compose restart`;
- banco SQLite com `integrity_check=ok`, migração `1` e os mesmos agentes após o restart;
- política `restart: unless-stopped`, volume nomeado e comando Uvicorn com `--workers 1`;
- `.env` ausente da imagem e token ausente dos logs, inclusive após handshake legado;
- projeto/volume temporários removidos após a validação.

## Rollout sem publicação automática

1. Pause a frota pelo master switch.
2. Gere/valide o backup SQLite e confirme `integrity_check`.
3. Atualize o hub e confirme `/health` e `/health/ready`.
4. Atualize o agente legado com `CONTROL_AGENT_ID=windows-desktop-01` e dry-run.
5. Valide hello, toggle, comando e cancelamento por PC.
6. Reative apenas os PCs autorizados e, por último, a frota.

Push, PR e deploy de produção permanecem ações explícitas do operador.
