# Fase 2D — seleção persistente e originais separados

**Decisão aprovada em 23/09/2026:** a esposa usa o Chrome como navegador padrão no MacBook. O lote entrega arquivos individuais; nenhum ZIP é criado no servidor ou exigido no MacBook. Safari mantém os links de download individual.

## Resultado esperado

Após autenticar via HTTPS, a usuária abre a viagem, seleciona assets e vê a contagem e o tamanho total. A seleção pertence ao usuário e continua após fechar o navegador e entrar novamente. “Baixar selecionados” pré-valida todos os originais e inicia uma transferência por asset. Cada card e detalhe também oferecem “Baixar original”. A interface explica que o Chrome pode pedir permissão para downloads múltiplos e não afirma que o arquivo chegou ao disco apenas porque a requisição começou.

## Persistência e autenticação

A migration 0005 adiciona User, UserSession e AssetSelection. User armazena username único e hash Argon2id; a senha inicial é digitada localmente com getpass por comando administrativo. UserSession guarda apenas o digest de um token aleatório, expiração, revogação e token CSRF. O cookie de sessão é HttpOnly, Secure, SameSite=Lax e host-only. Login só aceita HTTPS; credenciais reais não devem ser inseridas no HTTP atual. Logout revoga a sessão. Uma limitação simples por IP e usuário reduz tentativas repetidas de login. A proteção de catálogo e galeria é aplicada no servidor, inclusive thumbnails, proxies e downloads. Rotas de worker e /health mantêm o contrato atual.

Operações que mudam seleção ou sessão exigem token CSRF; login usa token anti-CSRF próprio. A sessão dura 12 horas sem renovação implícita. O servidor nunca registra senhas, tokens, caminhos físicos de mídia ou valores de cookies.

## Seleção e arquivos

PUT /api/catalog/assets/{asset_id}/selection marca ou desmarca de forma idempotente. A chave única é (user_id, catalog_asset_id). As páginas da galeria usam ação equivalente com formulário e token CSRF. A API retorna estado selecionado no asset e a contagem da viagem.

GET /api/catalog/assets/{asset_id}/download resolve somente o AssetFile(role=ORIGINAL) registrado para o asset_id. Exige disponibilidade AVAILABLE, path relativo seguro sob DMM_OMV_ROOT, arquivo regular presente e tamanho coerente com o catálogo quando conhecido. A resposta usa Content-Disposition attachment com nome editorial sanitizado e corpo transferido de arquivo, sem carregar o vídeo inteiro em RAM.

GET /api/catalog/trips/{slug}/selected-downloads verifica todos os originais da seleção antes de devolver a lista de URLs individuais, nomes únicos e tamanho total. Seleção vazia ou original indisponível retorna erro explícito e não inicia lote. Como arquivos podem mudar após a verificação, cada GET individual repete a validação; o lote é de melhor esforço, e a interface mantém os links individuais para recuperação. Nomes repetidos recebem sufixo estável do asset_id.

## Segurança de transporte

A configuração existente aceita certificados TLS no servidor e não precisa ampliar bind. Antes do aceite real, configurar e verificar HTTPS com certificado confiável no endereço privado usado pelo navegador. Cookie Secure sobre HTTP não resolve a exposição de credenciais. Se HTTPS não estiver disponível, o aceite com senha e downloads autenticados permanece pendente.

## Verificação

Cobrir migration upgrade/downgrade e constraints, hash e sessão, login/logout/expiração, CSRF, isolamento por usuário, seleção idempotente e persistente, acesso direto sem sessão, download de bytes originais, paths inválidos, symlink, nomes repetidos e regressão de filtros/Range. Executar pytest geral, Ruff e mypy. No Mac, fazer backup verificado do SQLite antes da migration, preservar .env/cache, aplicar a branch e validar três downloads separados com SHA-256 contra o catálogo. Registrar qualquer aceite que não seja executado como pendente.
