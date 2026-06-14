# Automatic Deploy

O servidor usa um timer systemd para checar `origin/main` a cada 2 minutos. Quando houver novo commit, ele executa `scripts/deploy.sh`, atualiza o checkout e roda `docker compose up -d --build`.

Arquivos:

- `scripts/deploy-if-needed.sh`: checa remoto, SHA local e health.
- `scripts/deploy.sh`: atualiza checkout, sobe Compose e valida `/health`.
- `ops/systemd/remotecontrol-auto-deploy.service`: unit oneshot.
- `ops/systemd/remotecontrol-auto-deploy.timer`: timer a cada 2 minutos.

Porta padrao no servidor: `8090`.

Validacoes:

```bash
systemctl status remotecontrol-auto-deploy.timer
systemctl start remotecontrol-auto-deploy.service
curl http://127.0.0.1:8090/health
```

