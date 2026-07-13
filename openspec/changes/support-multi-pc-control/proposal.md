## Why

O RemoteControl ainda funciona como um sistema single-agent na prática: a conexão WebSocket, settings, scheduler, comandos, eventos e console compartilham estado global. Isso faz uma segunda máquina substituir a primeira, permite interferência entre execuções e deixa corridas de reconnect, watchdog e cancelamento capazes de produzir automações órfãs ou resultados atribuídos ao PC errado.

Esta mudança transforma o hub em uma pequena frota multi-PC, mantendo a implantação simples escolhida para o projeto: FastAPI, SQLite, UI estática e uma única instância Uvicorn para até 10 PCs. O kill switch global, o token compartilhado e o modelo de acesso sem login serão preservados, com a exigência operacional de rede confiável ou VPN documentada.

## What Changes

- Introduzir registro persistente e em memória por `agent_id`, com sessão, heartbeat, configuração, agenda, fuso, histórico e execução isolados por PC.
- Migrar a configuração atual para `windows-desktop-01`; cadastrar novos agentes automaticamente como desativados e manter comandos/eventos antigos como legado não atribuído.
- Separar o master switch da frota do toggle individual e aplicar a regra efetiva `frota ativa AND PC ativo AND dentro da janela de trabalho`.
- Adicionar APIs de estado, settings com revisão/`ETag`, toggle, cancelamento e consultas paginadas por agente, mantendo aliases legados explícitos.
- Tornar WebSocket, hello, reconnect, watchdog, timeout e resultado resistentes a sessão antiga, queda de socket e concorrência entre PCs.
- Adicionar migração SQLite versionada/transacional, backup via API SQLite, integridade, índices agent-scoped, limite de um comando ativo por PC e retenção terminal de 90 dias.
- Reestruturar a console para resumo da frota e detalhe selecionável, com seleção persistente, proteção contra alterações não salvas, polling cancelável e renderização segura sem `innerHTML` dinâmico.
- Corrigir validação de settings, janelas aware com `ZoneInfo`, reinicialização de ritmo, housekeeping de timeout, eventos de conectividade por transição e cancelamento cooperativo.
- Adicionar liveness/readiness, shutdown limpo, heartbeat com jitter, backoff de reconnect, configuração Docker segura e documentação de rollout/rollback.
- Preservar os 80 testes atuais e ampliar a cobertura unitária, HTTP/WebSocket, migração, concorrência, segurança da UI, browser e carga de até 10 agentes.

## Capabilities

### New Capabilities

- `multi-agent-fleet-control`: Estado global da frota, cadastro/onboarding de agentes, settings e APIs de controle por PC, incluindo compatibilidade dos aliases legados.
- `agent-session-lifecycle`: Registro de sessões WebSocket, hello, heartbeat, reconnect, geração de sessão, isolamento de envio e entrega segura de resultados/cancelamentos.
- `isolated-agent-scheduling`: Scheduler por agente, janela de trabalho, fuso, ritmo, timeout calculado, cancelamento cooperativo e regra de execução efetiva.
- `command-event-persistence`: Migração e modelo SQLite versionados, comandos/eventos agent-scoped, validação, backup, integridade, concorrência, legado e retenção.
- `fleet-control-console`: Console multi-PC, seleção e edição protegidas, estados de loading/erro, polling eficiente, acessibilidade e renderização segura de dados dinâmicos.
- `runtime-readiness-deployment`: Health/readiness/liveness, shutdown e observabilidade do hub, comportamento de heartbeat/reconnect do agente, Docker e rollout operacional.

### Modified Capabilities

Nenhuma. O diretório `openspec/specs/` não possui capacidades principais publicadas; as mudanças de comportamento serão especificadas nas seis capacidades novas acima.

## Impact

- `hub/control_hub`: `main.py`, `agent_manager.py`, `scheduler.py`, `store.py`, `domain.py`, `rhythm.py`, migrações, modelos de validação, ciclo de vida e endpoints.
- `hub/control_hub/static`: console, polling, seleção de agente, formulários, histórico, CSP e acessibilidade.
- `windows_agent`: identidade obrigatória, hello compatível, heartbeat, jitter/backoff, execução fora da conexão e cancelamento seguro.
- `tests`: testes unitários, API, WebSocket, migração, concorrência, browser e carga.
- `docker-compose.yml`, `.dockerignore`, scripts e documentação de deploy/rollout.
- Contrato HTTP/WebSocket e esquema SQLite serão ampliados sem remover imediatamente as estruturas legadas; comandos legados ativos serão cancelados durante a migração.
