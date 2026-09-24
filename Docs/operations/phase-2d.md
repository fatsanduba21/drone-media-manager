# Fase 2D no Mac: login, seleção e downloads separados

A migration 0005_gallery_auth já faz parte do histórico do projeto. O lote entrega arquivos ORIGINAL separados, sem ZIP. O Chrome pode pedir permissão para downloads múltiplos; links individuais permanecem disponíveis para Chrome e Safari.

## Antes de usar credenciais: HTTPS

Preserve o bind e a porta atuais. Configure DMM_TLS_CERTFILE e DMM_TLS_KEYFILE no .env existente para um certificado confiável emitido para o nome DNS completo usado no Chrome. Restrinja a chave privada ao usuário do serviço. O servidor rejeita login e catálogo via HTTP com 426; cookie Secure sobre HTTP não resolve a exposição de credenciais.

No Tailscale, verifique o DNSName real com tailscale status --json e confirme MagicDNS e HTTPS Certificates na tailnet. Se aplicável, use tailscale cert --cert-file=CAMINHO_CERT --key-file=CAMINHO_CHAVE NOME_DNS_REAL. Acesse https://NOME_DNS_REAL:8000/gallery e teste o certificado sem ignorar erros: curl -fsS https://NOME_DNS_REAL:8000/health. Certificados salvos em arquivos exigem renovação; registre a expiração. Se o worker Windows usa http:// no mesmo endpoint, atualize DMM_SERVER_URL para o endereço https:// correspondente antes de retomá-lo. Sem certificado confiável, o aceite com senha fica pendente.

## Atualizar o checkout

No Mac, confirme o SSD e OMV montados. Inspecione git status --short e preserve alterações locais, .env, SQLite e cache. Não reimporte manifesto nem regenere derivados.

    cd /Volumes/SSDMacbook/desenvolvimento/drone-media-manager
    git status --short
    git fetch origin
    git pull --ff-only
    uv sync

Resolva um checkout sujo antes de atualizar a versão de produção.

## Backup verificado antes da migration

Execute no checkout. A API de backup do SQLite cria uma cópia consistente; o script não imprime secrets.

    uv run python - <<'PY'
    import sqlite3
    from datetime import datetime
    from drone_media_manager.config import get_server_settings

    database = get_server_settings().database_path.expanduser().resolve()
    backup = database.with_name(database.name + ".pre-2d-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".backup")
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(backup)
    with target:
        source.backup(target)
    result = target.execute("PRAGMA integrity_check").fetchone()[0]
    target.close()
    source.close()
    if result != "ok" or backup.stat().st_size == 0:
        raise SystemExit("Backup inválido; migração bloqueada")
    backup.chmod(0o600)
    print(f"Backup verificado: {backup} ({backup.stat().st_size} bytes)")
    PY

Confira o caminho, tamanho não zero e resultado ok antes de migrar. Guarde o backup em armazenamento local.

## Migrar e reiniciar

    uv run dmm-server migrate
    uv run python -c 'from drone_media_manager.cli.server import alembic_config, verify_database_revision; from drone_media_manager.config import get_server_settings; from drone_media_manager.db.session import create_engine_from_settings; s=get_server_settings(); e=create_engine_from_settings(s); verify_database_revision(e, alembic_config(s)); e.dispose(); print("revision ok")'
    launchctl kickstart -k "gui/$(id -u)/com.drone-media-manager.server"
    curl -fsS https://NOME_DNS_REAL:8000/health

Configure os caminhos TLS no .env antes do restart, sem apagar outras entradas. Aguarde a inicialização caso a porta ainda esteja fechada. O retorno healthy deve abranger banco, OMV, ffmpeg, ffprobe e worker. Não use curl -k para declarar HTTPS aceito.

## Usuário e aceite no Chrome

No terminal local do Mac, execute uv run dmm-server user create --username editor. Digite a senha duas vezes no prompt oculto (mínimo 12 caracteres). Não compartilhe nem registre a senha. No Chrome do MacBook, abra /gallery na URL HTTPS, entre, selecione três assets da viagem real e anote os asset_id. Feche e reabra o Chrome, entre novamente e confirme as três marcas e a contagem.

Clique em Baixar selecionados. Se o Chrome pedir permissão para vários downloads deste site, permita para usar o lote. Confirme três arquivos individuais no gerenciador de downloads, sem ZIP ou descompactação. Se algum for bloqueado, use o link Baixar correspondente no painel ou Baixar original no card/detalhe. O Safari pode usar os links individuais.

Compare o SHA-256 de cada arquivo com o sha256 do AssetFile ORIGINAL cadastrado, vinculando asset_id e nome editorial. No MacBook, shasum -a 256 CAMINHO_DO_ARQUIVO calcula o hash. No Mac servidor, consulte os três hashes catalogados (a consulta imprime apenas asset_id e SHA-256):

    db=$(uv run python -c 'from drone_media_manager.config import get_server_settings; print(get_server_settings().database_path)')
    sqlite3 "$db" "SELECT c.asset_id, f.sha256 FROM asset_selections s JOIN users u ON u.id=s.user_id JOIN catalog_assets c ON c.id=s.catalog_asset_id JOIN trips t ON t.id=c.trip_id JOIN asset_files f ON f.catalog_asset_id=c.id AND f.role='ORIGINAL' WHERE u.username='editor' AND t.slug='teste-fase-1' ORDER BY c.asset_id;"

Confirme que nenhum arquivo é thumbnail, proxy ou SRT. Teste também um download individual. Em janela anônima, a URL direta de original, thumbnail e proxy deve responder 401; /gallery deve enviar ao login. Confira /health no fim. Registre HEAD, backup, migration, certificado, contagem, hashes e resultados no checkpoint. Marque como pendente cada passo não executado no Mac.

## Downloads parados em 0 bytes no Mac mini

Se a galeria e as miniaturas carregam, mas o Chrome ou Brave mostram originais em 0 bytes indefinidamente, verifique primeiro a autorização de acesso ao volume pelo macOS no Mac mini. Neste caso real, o serviço iniciou via uv, e havia uma solicitação do macOS para permitir que uv acessasse o disco. Depois da autorização, os downloads funcionaram e os SHA-256 conferiram.

Um status 200 ou 206 nos logs de GET /download confirma apenas os cabeçalhos: o corpo pode continuar bloqueado. A leitura direta do arquivo pelo Terminal também pode funcionar enquanto o serviço lançado pelo LaunchAgent está aguardando permissão própria. Abra a sessão gráfica do Mac mini, procure o diálogo de permissão para uv e confira Ajustes do Sistema > Privacidade e Segurança. Após conceder a permissão, faça um download de teste e confira o SHA-256. Não altere Tailscale, TLS ou código antes de verificar esse bloqueio quando os sintomas coincidirem.
## Recuperação

Em falha, mantenha o backup intacto. Para voltar à versão anterior, pare o serviço, restaure a base verificada (considerando arquivos auxiliares SQLite), volte ao commit anterior e execute uv sync correspondente antes do restart. Não apague mídia, cache nem .env. A restauração elimina seleções criadas após o backup.
