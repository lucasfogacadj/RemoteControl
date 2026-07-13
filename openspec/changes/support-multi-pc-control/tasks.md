## 1. Baseline e contratos

- [x] 1.1 Registrar o baseline do checkout atual: `pytest`, `compileall`, `node --check` e `docker compose config`, preservando a referência dos 80 testes existentes.
- [x] 1.2 Fixar fixtures do protocolo atual, do banco singleton, dos aliases `/api/state`, `/api/settings` e `/api/toggle`, e do agente legado para orientar compatibilidade e rollback.
- [x] 1.3 Definir constantes compartilhadas para `windows-desktop-01`, formato/validação de `agent_id`, versão do protocolo, estados aceitos, cursor e endpoints de liveness/readiness.

## 2. Persistência e migração SQLite

- [x] 2.1 Criar controle de versões de migração, transações idempotentes, WAL/busy timeout e fechamento explícito da conexão no shutdown.
- [x] 2.2 Implementar backup consistente pela API SQLite e `integrity_check` antes da primeira migração, com falha bloqueando a alteração e a readiness.
- [x] 2.3 Criar `fleet_state` e `agent_settings` com `enabled`, JSON, `revision` e timestamps, além dos metadados persistidos necessários ao estado do agente.
- [x] 2.4 Adicionar `agent_id`, `session_id` e `deadline_at` aos comandos e `agent_id`/`command_id` aos eventos, preservando colunas/estruturas legadas na primeira versão.
- [x] 2.5 Criar índices por agente/status/data/cursor e a restrição transacional de no máximo um comando ativo por `agent_id` não nulo.
- [x] 2.6 Implementar o backfill da configuração atual para `windows-desktop-01`, preservar rows sem agente como legado não atribuído e cancelar comandos legados ativos.
- [x] 2.7 Marcar sessões persistidas offline no startup e implementar retenção em lotes de comandos/eventos terminais com mais de 90 dias, sem excluir ativos.
- [x] 2.8 Adicionar testes de migração idempotente, interrupção/retry, backup restaurável, `integrity_check`, legado não atribuído, cancelamento de legado, índices e retenção.

## 3. Domínio e validação estrita

- [x] 3.1 Substituir a validação permissiva de settings por modelos estritos com campos extras proibidos e booleanos reais, cobrindo o caso `"false"`.
- [x] 3.2 Validar IDs de rotina únicos e allowlisted, labels gerados pelo servidor, números finitos/limitados, enumerações existentes e payloads declarativos.
- [x] 3.3 Adicionar `work_start`, `work_end` e `timezone` aos defaults e validar `ZoneInfo`, janela no mesmo dia, horários aware e a configuração padrão `08:30–18:30 America/Sao_Paulo`.
- [x] 3.4 Implementar estimativa de duração por payload, margem de 50% + 15 s, 10 s de grace do hub e rejeição do pior caso acima de 1.800 s.
- [x] 3.5 Cobrir a validação com testes para strings booleanas, extras, rotinas duplicadas, labels adulterados, `NaN`/infinito, limites, timezone inválido e janela cruzando meia-noite.

## 4. Registro de sessões e isolamento de agentes

- [x] 4.1 Transformar `AgentManager` em registry `agent_id -> AgentSession` com `session_id`, geração, heartbeat, WebSocket e lock de envio por agente.
- [x] 4.2 Implementar conexão/reconexão que substitui somente a sessão do mesmo agente, com limpeza condicional por geração e coexistência comprovada de dois a dez agentes.
- [x] 4.3 Implementar watchdog por sessão, derivação de online pela conexão viva e eventos de conectividade somente em transições.
- [x] 4.4 Extrair o slot de execução do ciclo de vida do WebSocket, com cancelamento cooperativo, espera terminal e bloqueio de novo comando até o worker anterior terminar.
- [x] 4.5 Adicionar testes unitários de dois agentes simultâneos, reconnect do mesmo ID, heartbeat antigo, falha de envio, watchdog e ausência de duas automações no mesmo PC.

## 5. Protocolo WebSocket e agente Windows

- [x] 5.1 Tornar `CONTROL_AGENT_ID` obrigatório e validado no agente novo, atualizar `.env.example`/documentação para `windows-desktop-01` e impedir defaults que colidam entre PCs.
- [x] 5.2 Implementar hello com `agent_id`, `name`, `version`, `protocol`, `dry_run` e `capabilities`, mantendo adapter de leitura para clientes legados.
- [x] 5.3 Versionar/correlacionar envelopes de comando, heartbeat e resultado com `agent_id`, `session_id`, `command_id` e `deadline_at`.
- [x] 5.4 Refatorar o worker do agente para sobreviver à lógica de conexão apenas como slot controlado, cancelar rotina ao cair o socket e aguardar encerramento antes de aceitar nova execução.
- [x] 5.5 Aceitar apenas estados de resultado conhecidos e tratar resultado de sessão antiga, PC divergente, comando terminal ou desconhecido como `late_result`/erro auditável.
- [x] 5.6 Adicionar jitter limitado ao heartbeat e backoff exponencial com teto/reset após conexão, sem expor token nos logs ou no `print-config`.
- [x] 5.7 Atualizar testes dry-run e WebSocket do agente para hello, identidade, cancelamento durante rotina, queda do socket, resultado tardio, jitter e backoff.

## 6. Store de comandos, eventos e cursores

- [x] 6.1 Refatorar leitura/escrita de settings, estado, comandos e eventos para receber `agent_id` explícito e remover dependência do “último heartbeat”.
- [x] 6.2 Implementar transições condicionais de queued/dispatched/running/terminal por comando, agente e sessão, protegendo cancelamento, timeout e resultado tardio.
- [x] 6.3 Implementar deduplicação de eventos de offline/bloqueio e associação de eventos a `agent_id` e `command_id`.
- [x] 6.4 Implementar listagens paginadas por `(created_at,id)` com cursor estável para `/api/events` e `/api/commands`, incluindo filtro de agente e legado.
- [x] 6.5 Testar corridas de envio/reconnect/watchdog, resultado falsificado por outro PC, lost update de comando, estados desconhecidos, cursores e isolamento de histórico.

## 7. Scheduler de frota

- [x] 7.1 Transformar `RoutineScheduler` em scheduler de frota com runtime por agente, `next_run`, revisão observada e `RhythmEngine` independente.
- [x] 7.2 Implementar avaliação com `ZoneInfo` e datetimes aware, janela explícita same-day, defaults por agente e perfil influenciando ritmo sem definir jornada.
- [x] 7.3 Executar housekeeping de timeout no início de todo tick, independentemente do próximo agendamento, usando deadline individual e cálculo de teto.
- [x] 7.4 Aplicar a regra de três gates e impedir criação/envio para agente offline, disabled, master off ou fora da janela.
- [x] 7.5 Cancelar cooperativamente por master off, toggle individual e fechamento da janela, com atualização condicional e sem transformar cancelado em sucesso.
- [x] 7.6 Resetar plano/ritmo/next run somente do agente cuja settings, jornada ou fuso mudou.
- [x] 7.7 Garantir um comando ativo por PC sem bloquear comandos de PCs distintos e registrar conectividade/bloqueios somente em transições.
- [x] 7.8 Adicionar testes de dois a dez agentes, master off, toggle individual, janela, fusos, DST/boundaries, alteração no mesmo dia, timeout por payload, cancelamento e ausência de spam de eventos.

## 8. APIs HTTP e compatibilidade

- [x] 8.1 Implementar `GET /api/fleet/state` e `GET /api/agents/{agent_id}/state` com resumo da frota e detalhe estritamente agent-scoped.
- [x] 8.2 Implementar `PUT /api/agents/{agent_id}/settings` com `ETag`/revisão, precondição, resposta de conflito e retorno da nova versão.
- [x] 8.3 Implementar `POST /api/agents/{agent_id}/toggle` alterando somente `enabled` e `POST /api/agents/{agent_id}/cancel` idempotente e isolado.
- [x] 8.4 Implementar `GET /api/events` e `GET /api/commands` com `agent_id`, cursor, ordenação estável e marcador explícito para legado não atribuído.
- [x] 8.5 Preservar `POST /api/toggle` como master kill switch e `/api/state`/`/api/settings` como aliases fixos de `windows-desktop-01`.
- [x] 8.6 Atualizar o handler WebSocket para validar hello, geração, ownership, estados conhecidos, heartbeat e resultado tardio antes de persistir qualquer mudança.
- [x] 8.7 Adicionar testes HTTP e WebSocket para contratos, 404, ETag/lost update, isolamento, aliases, cursor, toggle/cancel concorrentes e falsificação cross-agent.

## 9. Console multi-PC e segurança web

- [x] 9.1 Redesenhar HTML/CSS para resumo de frota, lista selecionável, detalhe, histórico, toggle/cancel individual e “Pausar todos” permanentemente visível.
- [x] 9.2 Implementar estado de seleção persistido no navegador e bloqueio explícito de troca quando o formulário estiver sujo.
- [x] 9.3 Separar renderizadores seguros de fleet/detail/history e substituir `innerHTML` dinâmico por criação de nós/`textContent`.
- [x] 9.4 Adicionar CSP compatível com a UI e revisar qualquer origem dinâmica de labels, IDs, eventos, mensagens e comandos contra XSS.
- [x] 9.5 Separar polling leve da frota e do detalhe, usar `AbortController`, ignorar respostas obsoletas e suspender polling com `visibilitychange`.
- [x] 9.6 Implementar estados loading/erro/retry, conflito de revisão sem perder edição, `aria-pressed`, foco visível, teclado e alvos mínimos de 44 px.
- [x] 9.7 Criar testes browser em 375, 768 e desktop para seleção, persistência, dirty form, master pause, toggle/cancel, erro, conflito, polling oculto e XSS.

## 10. Saúde, shutdown e runtime de deploy

- [x] 10.1 Preservar `/health` e adicionar liveness/readiness com checks separados de processo, SQLite/migração, scheduler e watchdog, sem falhar por agente offline.
- [x] 10.2 Integrar shutdown do FastAPI para parar loops, cancelar/aguardar slots dentro do budget, marcar sessões offline e fechar SQLite.
- [x] 10.3 Atualizar `.dockerignore`, `docker-compose.yml` e comando Uvicorn para excluir `.env`, manter volume/restart e declarar um único worker.
- [x] 10.4 Documentar token compartilhado em rede confiável/VPN, identidade por PC, onboarding desativado, dry-run, backup, rollout pausado e rollback.
- [x] 10.5 Validar `docker compose config`, build e startup/restart local sem perda da base ou exposição de segredo.

## 11. Verificação integrada e aceite

- [x] 11.1 Rodar a suíte existente e confirmar que os 80 testes anteriores continuam passando após a refatoração.
- [x] 11.2 Rodar testes unitários de domínio, store, migração, AgentManager, scheduler, agente e validação estrita.
- [x] 11.3 Rodar testes HTTP/WebSocket de onboarding, dois a dez agentes, comandos paralelos, isolamento de settings/timeout/resultado/cancelamento e restart offline.
- [x] 11.4 Rodar cenários de reconnect durante envio/watchdog, socket quebrado, queda durante rotina e garantir ausência de automação órfã ou concorrente no mesmo PC.
- [x] 11.5 Rodar cenários de master off, toggle individual, fechamento de jornada, fusos, mudança no mesmo dia, novo PC disabled, legado, backup restaurável e migração idempotente.
- [x] 11.6 Rodar casos de segurança para `"false"`, duplicidade, infinito, lost update, XSS, estado desconhecido e resultado falsificado por outro PC.
- [x] 11.7 Executar carga de 10 agentes com heartbeat de 1 s e retenção, verificando ausência de `database is locked`, spam de eventos e degradação da API da frota.
- [x] 11.8 Executar `pytest`, `compileall`, `node --check`, validação OpenSpec, `docker compose config`, build e E2E nos três breakpoints.
- [x] 11.9 Atualizar quickstart/relatório de validação com comandos executados, resultados, limitações conhecidas e passos de rollout sem fazer push, PR ou deploy.
