## Context

O hub atual é um processo FastAPI com SQLite, UI estática e um único scheduler. Embora o agente já envie `agent_id`, o `AgentManager` guarda somente um WebSocket, as settings usam uma linha singleton, e comandos, eventos, timeout e estado do agente são consultados globalmente. Uma reconexão pode substituir a conexão anterior e o ciclo de vida da execução está acoplado à conexão que a iniciou.

O alvo é uma frota pequena, de até 10 PCs, atendida por uma única instância Uvicorn. O desenho precisa preservar o contrato operacional atual (token compartilhado, UI/API sem login e `/health`), mas separar claramente estado global da frota, estado por agente, identidade da sessão e execução local. A porta deverá permanecer em rede confiável ou VPN; esta mudança não cria autenticação de operador.

## Goals / Non-Goals

**Goals:**

- Isolar configuração, agenda, conexão, execução, histórico, timeout e cancelamento por `agent_id`.
- Preservar um master switch global e aplicar a regra `frota ativa AND PC ativo AND dentro da janela de trabalho`.
- Migrar a instalação atual para `windows-desktop-01`, permitir onboarding automático desativado e manter rollback possível.
- Garantir que reconnect, watchdog e resultados tardios não cruzem sessões ou PCs.
- Manter SQLite/WAL, UI estática e um único worker, com desempenho verificável para 10 agentes e heartbeat de 1 s.
- Entregar contratos testáveis para API, WebSocket, migração, console, saúde e rollout.

**Non-Goals:**

- Criar login, RBAC, novo sistema de tokens ou substituir o modelo de rede confiável/VPN.
- Transformar o hub em serviço distribuído, adicionar múltiplos workers ou trocar SQLite por outro banco.
- Aceitar janelas que atravessem a meia-noite na primeira versão.
- Permitir scripts arbitrários; os comandos continuam declarativos e limitados às rotinas existentes.
- Fazer rollout, push, PR ou deploy de produção como parte da implementação sem autorização específica.

## Decisions

### 1. Registro de agentes e ciclo de sessão

`AgentManager` será um registro `agent_id -> AgentSession`. Cada sessão terá `session_id` UUID, geração monotônica, WebSocket, último heartbeat, estado de conexão e lock de envio próprio. A operação de conectar substituirá somente a sessão do mesmo `agent_id`; uma conexão de outro PC nunca fechará nem limpará o primeiro.

O slot de execução será separado do objeto WebSocket. Ele manterá o `command_id` ativo, o evento de cancelamento e a tarefa/worker responsável pela automação. Quando o socket cair, o hub cancelará cooperativamente o slot, aguardará seu encerramento terminal e somente depois permitirá que uma reconexão do mesmo PC aceite novo comando. O scheduler continuará podendo registrar o PC como online apenas quando houver conexão viva.

O agente novo exigirá `CONTROL_AGENT_ID` não vazio, normalizado e único entre sessões vivas. O primeiro valor migrado será `windows-desktop-01`. O hello conterá `name`, `version`, `protocol`, `dry_run` e `capabilities`, além da identidade do agente, e será aceito por uma camada compatível com clientes legados. Mensagens de sessão antiga serão ignoradas ou registradas como tardias, nunca aplicadas ao comando da sessão nova.

Alternativa considerada: manter uma variável global com “o último WebSocket”. Foi rejeitada porque a segunda conexão expulsa o primeiro PC e não permite isolamento de watchdog, envio ou resultado.

### 2. Persistência versionada e compatibilidade de dados

Uma migração versionada e transacional criará `fleet_state` como singleton do master switch e `agent_settings` keyed by `agent_id`, com `enabled`, JSON validado, `revision`, `created_at` e `updated_at`. O estado persistido do agente guardará identidade e último heartbeat, mas `online` será derivado da conexão viva e todas as sessões persistidas serão marcadas offline no startup.

`commands` receberá `agent_id` nullable, `session_id` nullable, `deadline_at` e os metadados necessários para estado terminal. `events` receberá `agent_id` nullable e `command_id` nullable. Rows antigas sem agente serão preservadas como legado não atribuído; comandos legados ainda ativos serão cancelados durante o backfill. Índices cobrirão `(agent_id, status, created_at)`, `(agent_id, updated_at)` e cursores por data/id. Um índice parcial ou equivalente transacional garantirá no máximo um comando ativo por agente.

Antes da primeira migração, o hub fará backup consistente pela API de backup do SQLite, executará `integrity_check` e só então aplicará a versão dentro de uma transação. As tabelas/colunas legadas permanecerão na primeira versão para rollback. A retenção removerá apenas comandos e eventos terminais com mais de 90 dias, em lotes limitados, sem tocar em comandos ativos.

Alternativas consideradas: recriar a base do zero ou usar um banco externo. Foram rejeitadas porque perdem histórico/rollback ou violam a implantação simples para uma frota de 10 PCs.

### 3. Scheduler de frota, relógio e timeout

O scheduler manterá estado de agenda por agente (`next_run`, revisão observada e instância do `RhythmEngine`) e percorrerá todos os agentes cadastrados em cada tick. Housekeeping de timeout ocorrerá no início de todo tick, mesmo quando nenhum `next_run` estiver vencido. O próximo agendamento de um agente não bloqueará timeout ou execução de qualquer outro.

`work_start`, `work_end` e `timezone` serão settings por agente, com defaults `08:30`, `18:30` e `America/Sao_Paulo`. A primeira versão aceitará somente janela no mesmo dia e datetimes aware com `ZoneInfo`. O perfil continuará alterando ritmo, energia e multiplicadores de rotina, mas não será a fonte da jornada. Mudança de settings, jornada ou fuso invalidará o plano do dia e reinicializará o ritmo daquele agente.

Para cada comando, o hub estimará a duração a partir do payload, calculará `execution_budget = ceil(estimativa * 1.5 + 15s)` e registrará `deadline_at = now + execution_budget + 10s`. O pior caso, incluindo a margem extra do hub, deverá ser no máximo 1.800 s; settings que possam exceder esse teto serão rejeitadas. Timeout, cancelamento por master off, toggle individual ou fechamento da janela serão atualizados condicionalmente pelo par `command_id`/sessão, e o comando cancelado nunca poderá virar sucesso.

Alternativa considerada: um único intervalo e um único timeout globais. Foi rejeitada porque um PC lento ou uma rotina longa bloquearia a frota e porque o perfil atual mistura jornada com ritmo.

### 4. Validação e concorrência de settings

Settings serão parseadas por modelos estritos: booleanos precisam ser booleanos reais, campos extras serão proibidos, IDs de rotina serão únicos e pertencentes à allowlist, labels serão produzidos pelo servidor e números deverão ser finitos e estar dentro dos limites da rotina. A validação cobrirá explicitamente valores como string `"false"`, `NaN` e infinito.

`PUT /api/agents/{agent_id}/settings` exigirá a revisão atual por `ETag` ou campo equivalente e responderá conflito sem sobrescrever alteração concorrente. O toggle individual terá operação própria e alterará somente `enabled`; não poderá substituir o JSON completo nem incrementar settings não relacionadas. O scheduler observará a revisão persistida para resetar seu estado.

### 5. API e contrato de compatibilidade

O contrato novo separará resumo e detalhe: `/api/fleet/state`, `/api/agents/{agent_id}/state`, settings/toggle/cancel por agente e consultas de events/commands com `agent_id` e cursor. `/api/toggle` continuará sendo o master kill switch. `/api/state` e `/api/settings` continuarão temporariamente como aliases do PC legado explícito `windows-desktop-01`; nunca serão resolvidos para “último heartbeat”.

Resultados WebSocket só serão aceitos se `command_id`, `agent_id` e `session_id` coincidirem com o registro ativo e se o estado pertencer ao conjunto conhecido. Respostas incompatíveis, de outra máquina ou tardias serão auditadas como `late_result`/rejeitadas sem alterar o comando. O estado `unknown` não será persistido como sucesso ou falha final.

### 6. Console e segurança da superfície web

A UI terá resumo da frota, lista selecionável de agentes, detalhe do PC escolhido, toggle individual, cancelamento, settings e histórico. “Pausar todos” ficará sempre visível. O `agent_id` selecionado será persistido no navegador; se o formulário estiver sujo, a troca será bloqueada até salvar ou descartar explicitamente.

O polling será separado entre frota e detalhe, usará `AbortController` para cancelar requests obsoletos e será suspenso enquanto a página estiver oculta. Conteúdo vindo de settings, eventos, comandos ou agentes será criado com nós DOM e `textContent`; não haverá `innerHTML` dinâmico para dados externos. A resposta HTML incluirá CSP compatível com a UI, e controles terão estados loading/erro, `aria-pressed`, foco visível e área de interação mínima de 44 px.

Alternativa considerada: manter o renderizador atual e apenas adicionar cards. Foi rejeitada porque amplia o caminho de XSS já existente e torna troca de agente/polling concorrente ambígua.

### 7. Saúde, shutdown e operação do agente

`/health` continuará compatível. Liveness e readiness indicarão separadamente processo, SQLite/migração, scheduler e watchdog; agente offline será estado operacional e não indisponibilidade do hub. O shutdown cancelará loops, aguardará slots de execução dentro do limite, fechará SQLite e deixará sessões persistidas offline.

O agente aplicará jitter ao heartbeat e backoff exponencial com limite na reconexão. O Docker excluirá `.env` do contexto, configurará restart do container e manterá explicitamente um único worker Uvicorn. A documentação descreverá token compartilhado em rede confiável/VPN, backup, pausa, dry-run, reativação e rollback.

## Risks / Trade-offs

- [Automação GUI pode não interromper imediatamente após queda do socket] → Manter slot fora da conexão, usar cancelamento cooperativo em todas as rotinas, aguardar término antes de aceitar novo comando e registrar timeout/cancelamento sem converter resultado tardio em sucesso.
- [SQLite pode sofrer contenção com 10 agentes e heartbeat de 1 s] → Usar WAL, timeout de busy, transações curtas, índices agent-scoped, atualização somente em mudanças relevantes e teste de carga sem `database is locked`.
- [Cliente legado não carrega identidade de sessão] → Associá-lo somente ao agente legado explícito, preservar adapter temporário e impedir que envelopes sem correlação atualizem comandos novos.
- [Mudança de fuso e DST pode deslocar a janela] → Usar `ZoneInfo`, datetimes aware, conversão para UTC na persistência e testes nos limites da janela e em transições de horário.
- [Token compartilhado e UI sem login deixam a porta sensível na rede] → Documentar bind/uso somente em rede confiável ou VPN, não ampliar exposição e manter o token fora do código e da imagem.
- [Migração interrompida pode deixar dados parcialmente convertidos] → Backup via API SQLite, `integrity_check`, versão transacional, migração idempotente e estruturas legadas preservadas para rollback.
- [Seleção rápida de PC pode exibir resposta de um request antigo] → Cancelar requests anteriores, associar respostas ao `agent_id` selecionado e não sobrescrever formulário sujo.
- [Retenção pode gerar picos de lock ou apagar evidência útil] → Apagar em lotes pequenos, apenas estados terminais, nunca comandos ativos, e registrar métricas/resultado do housekeeping.

## Migration Plan

1. Congelar a frota com o master switch desligado e confirmar que não há comando ativo inesperado.
2. Criar o backup consistente pela API SQLite, validar que é restaurável e executar `PRAGMA integrity_check` na origem e no backup.
3. Parar/atualizar o hub com a migração versionada. Criar `fleet_state` e `agent_settings`, migrar settings para `windows-desktop-01`, cancelar comandos legados ativos e manter as estruturas antigas.
4. Inicializar o novo hub com todas as sessões persistidas offline, validar liveness/readiness, scheduler, watchdog e aliases legados, sem reativar a frota.
5. Atualizar o agente existente com `CONTROL_AGENT_ID=windows-desktop-01`, hello compatível e `dry_run=true`; validar heartbeat, estado, comando, cancelamento e resultado correlacionado.
6. Cadastrar agentes adicionais por conexão/hello e confirmar que cada um nasce desativado, sem alterar settings ou execução dos demais. Executar a matriz de dois a dez agentes e os testes browser/responsivos.
7. Após a validação em dry-run, reativar o master switch e depois somente os PCs autorizados. Habilitar retenção após observar a primeira janela operacional.

O rollback interrompe o scheduler, mantém o master desligado, restaura o backup somente se necessário e retorna ao artefato anterior; as estruturas legadas permitem leitura/compatibilidade durante a primeira versão. Nenhum push, PR ou deploy de produção será feito automaticamente.

## Open Questions

Não há decisão de produto bloqueante pendente. Durante a implementação serão fixados apenas parâmetros operacionais de tuning (tamanho do lote de retenção, intervalos de polling e limites de backoff), desde que respeitem os contratos e tetos definidos nesta mudança.
