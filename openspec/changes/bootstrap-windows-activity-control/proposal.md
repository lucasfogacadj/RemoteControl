## Why

O projeto precisa transformar uma ideia de automacao remota em um sistema operavel, auditavel e containerizado, com configuracao local simples e limites claros de autorizacao. O objetivo e permitir rotinas controladas em um computador Windows proprio ou autorizado, sem depender de controle fragil da interface do AnyDesk a partir de um container headless.

## What Changes

- Criar um hub web local, executado em container no Ubuntu Server, para ativar/desativar o uso, configurar rotinas e acompanhar estado.
- Criar um agente Windows instalado explicitamente na maquina controlada para executar apenas acoes permitidas.
- Criar um motor de rotinas com pesos percentuais configuraveis para VS Code, Discord e Chrome/Gmail.
- Restringir a digitacao aleatoria a um arquivo de trabalho configurado no VS Code, nunca ao aplicativo ativo por acidente.
- Registrar execucoes, erros e estado do agente para inspecao pela interface local.
- Empacotar o hub com Docker Compose e fornecer instrucoes de execucao no Ubuntu Server.

## Capabilities

### New Capabilities
- `control-hub`: API, persistencia e interface web local para configuracao, ativacao e observabilidade.
- `windows-agent`: agente autenticado para executar acoes no Windows com allowlist de programas, arquivo e URLs.
- `routine-scheduler`: selecao ponderada de rotinas, janelas de execucao, pausas e limites de seguranca.
- `deployment-runtime`: empacotamento Docker, configuracao por variaveis de ambiente e documentacao de deploy no Ubuntu Server.

### Modified Capabilities
- Nenhuma.

## Impact

- Novo monorepo com backend/API, frontend web, agente Windows, Docker Compose e documentacao operacional.
- Dependencias previstas: Python/FastAPI no hub, React/Vite na interface, SQLite para persistencia local, WebSocket para comunicacao hub-agente e bibliotecas Windows de automacao no agente.
- AnyDesk permanece como canal manual de acesso/suporte ao Windows, nao como mecanismo programatico de automacao.
- O sistema deve exigir token de pareamento e deixar visivel quando uma rotina estiver ativa.
