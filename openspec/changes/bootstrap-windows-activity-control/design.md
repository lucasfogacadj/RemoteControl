## Context

Este e um projeto novo. O usuario quer um sistema que rode em container em um Ubuntu Server, tenha interface web local e controle rotinas em um computador Windows acessivel por AnyDesk. A decisao central e separar orquestracao de automacao: o Ubuntu executa o hub e a UI; o Windows executa um agente local autorizado, pois automacao de GUI precisa acontecer na sessao interativa do proprio Windows.

AnyDesk fica como canal manual de suporte e acesso remoto. O sistema nao tenta dirigir a janela do AnyDesk dentro do container, porque isso e fragil em ambiente headless, dificulta auditoria e pode acionar comandos no alvo errado.

## Goals / Non-Goals

**Goals:**
- Rodar o hub em Docker Compose no Ubuntu Server.
- Expor uma UI web local para ligar/desligar rotinas e configurar percentuais.
- Manter comunicacao autenticada entre hub e agente Windows.
- Executar rotinas allowlisted: digitar texto aleatorio em um arquivo especifico do VS Code, abrir/focar Discord e abrir/focar Chrome no Gmail.
- Registrar comandos, execucoes, erros e heartbeat do agente.
- Permitir desligamento imediato das rotinas pela UI.

**Non-Goals:**
- Automatizar AnyDesk como mecanismo de controle programatico.
- Coletar, armazenar ou preencher credenciais do Gmail, Discord, AnyDesk ou Windows.
- Executar acoes invisiveis, persistentes sem consentimento, ou destinadas a burlar politicas de monitoramento.
- Controlar aplicativos fora da allowlist configurada.
- Garantir funcionamento em sessao Windows bloqueada; rotinas de GUI exigem sessao interativa ativa.

## Decisions

1. Hub FastAPI com SQLite e UI estatica servida pelo proprio backend.
   - Rationale: reduz quantidade de containers, simplifica deploy no Ubuntu e atende a interface local.
   - Alternative considered: frontend React/Vite separado. Melhor para UI grande, mas adiciona complexidade desnecessaria no primeiro incremento.

2. Agente Windows em Python separado do container.
   - Rationale: bibliotecas de automacao de GUI precisam acessar a sessao do desktop Windows. Um servico headless ou container Linux nao tem essa capacidade de forma confiavel.
   - Alternative considered: controlar o AnyDesk via Xvfb no Ubuntu. Rejeitado por fragilidade, risco de foco errado e baixa auditabilidade.

3. Comunicacao outbound do agente por WebSocket.
   - Rationale: evita abrir porta inbound no Windows, permite heartbeat e entrega de comandos em tempo quase real.
   - Alternative considered: polling HTTP. Mais simples, mas pior para controle imediato e estado online/offline.

4. Percentuais sao configurados no hub e normalizados pelo scheduler.
   - Rationale: a UI pode validar total de 100% para clareza, enquanto o backend usa a mesma regra para escolher rotinas.
   - Alternative considered: pesos livres sem soma. Mais flexivel, porem menos alinhado ao pedido de porcentagem por programa.

5. Rotinas executam somente comandos declarativos.
   - Rationale: o hub envia intencoes allowlisted, como `vscode_type_random_text`, `open_discord` e `open_gmail`; o agente decide como executar de modo local e validado.
   - Alternative considered: enviar scripts arbitrarios. Rejeitado por risco operacional e de seguranca.

## Risks / Trade-offs

- [Sessao Windows bloqueada impede automacao de GUI] -> Documentar requisito de sessao interativa e expor erro claro no agente.
- [Foco de janela incorreto pode causar digitacao no lugar errado] -> Abrir arquivo alvo do VS Code antes de digitar, aguardar foco e limitar texto ao arquivo configurado.
- [Token compartilhado vazado permitiria comandos no agente] -> Usar segredo por variavel de ambiente, nunca commitar `.env`, e permitir rotacao.
- [Percentuais invalidos confundem selecao] -> UI e API validam soma total de 100% para rotinas habilitadas.
- [Abertura de Gmail depende de login existente no Chrome] -> O agente apenas abre a URL; credenciais e sessoes ficam fora do sistema.

## Migration Plan

1. Criar monorepo com `hub/`, `windows-agent/`, `docs/` e arquivos Docker.
2. Implementar o hub com estado local, API REST, WebSocket de agente e UI web.
3. Implementar agente Windows com modo `--dry-run` e execucao real opcional.
4. Validar localmente o hub via Docker Compose.
5. Instalar o agente no Windows via ambiente Python e token pareado.
6. Rollback: parar `docker compose`, remover volume SQLite se necessario e encerrar o agente Windows.

## Open Questions

- Caminho exato do arquivo que o VS Code deve abrir e receber texto aleatorio.
- Se a UI deve ficar acessivel apenas em `localhost`/VPN ou tambem na rede local.
- Intervalos padrao desejados entre rotinas e horarios em que o sistema deve permanecer pausado.
