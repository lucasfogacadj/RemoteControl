# Windows Agent Setup

Este agente deve rodar na maquina Windows autorizada, dentro de uma sessao interativa. Rotinas que digitam ou abrem aplicativos nao funcionam de forma confiavel em sessao bloqueada ou em servico headless.

## Requisitos

- Windows com Python 3.11+.
- VS Code instalado e acessivel pelo comando configurado em `VSCODE_EXECUTABLE`.
- Discord e Chrome instalados se as rotinas correspondentes forem usadas.
- Sessao Windows desbloqueada e visivel para rotinas de click do mouse.
- Acesso de rede do Windows para o hub no Ubuntu Server.

## Instalar

```powershell
cd D:\Projetos\control
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r windows_agent\requirements.txt
```

## Configurar

Copie os valores de `windows_agent/.env.example` para variaveis de ambiente da sessao ou para um script local privado. Nao commite segredos.

```powershell
$env:CONTROL_HUB_WS_URL="ws://SEU_UBUNTU_SERVER:8080/ws/agent"
$env:CONTROL_PAIRING_TOKEN="troque-este-token"
$env:CONTROL_AGENT_ID="windows-desktop-01"
$env:CONTROL_AGENT_DRY_RUN="true"
$env:VSCODE_TARGET_FILE="C:\Temp\control-typing.txt"
```

Crie o arquivo alvo antes de habilitar execucao real:

```powershell
New-Item -ItemType Directory -Force C:\Temp
New-Item -ItemType File -Force C:\Temp\control-typing.txt
```

## Validar em dry-run

```powershell
python -m windows_agent.agent --print-config
python -m windows_agent.agent
```

Com `CONTROL_AGENT_DRY_RUN=true`, o agente conecta, envia heartbeat e responde comandos sem abrir programas.

## Execucao real

Depois de validar o dry-run:

```powershell
$env:CONTROL_AGENT_DRY_RUN="false"
python -m windows_agent.agent
```

Mantenha a sessao Windows desbloqueada e visivel. O agente abre o arquivo configurado no VS Code antes de digitar, mas automacao de GUI ainda depende do foco real da sessao.

Clicks de mouse sao configurados no hub com coordenadas absolutas da tela, botao (`left`, `right` ou `middle`) e quantidade de clicks. Revise esses valores em dry-run antes de ativar execucao real, especialmente em ambientes com mais de um monitor ou mudanca de resolucao. Nao use os cantos da tela como alvo de click: o PyAutoGUI usa os cantos como fail-safe. Se o fail-safe disparar, mova o cursor para fora dos cantos antes de retomar a automacao.

## Inicializacao no logon

Para uso recorrente, crie uma tarefa no Agendador de Tarefas que rode no logon do usuario interativo. Use um script `.ps1` privado para carregar as variaveis e iniciar:

```powershell
cd D:\Projetos\control
.\.venv\Scripts\python.exe -m windows_agent.agent
```
