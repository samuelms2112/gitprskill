# PR Insights — Gestão de Pull Requests com IA

Plataforma multi-tenant que importa Pull Requests do GitHub, calcula métricas de engenharia (tamanho,
tempo até o merge), gera análises com IA (resumo, categoria, risco, parecer de produto) e faz a
revisão automática dos PRs com as regras de cada empresa.

- **Backend:** FastAPI + SQLAlchemy (PostgreSQL com pgvector) + Celery (Redis).
- **Frontend:** Next.js (App Router), Tailwind e componentes no padrão shadcn.
- **IA:** Claude Code CLI autenticado com a assinatura do Claude (`claude -p`), sem chave de API.
  Gemini está disponível como alternativa (`AI_PROVIDER=gemini`).
- **Produção:** Docker Compose atrás do Caddy (HTTPS automático), num servidor Ubuntu 24.04.

---

## 1. Pré-requisitos

Antes de instalar, você precisa de:

| Item | Para quê |
|---|---|
| Servidor Ubuntu 24.04 (recomendado: 4 vCPU e 8 GB de RAM) | Produção |
| Domínio com registro DNS `A` apontando para o IP do servidor | HTTPS e callbacks do GitHub |
| Conta no GitHub com permissão de administrador na organização | Criar o GitHub App e o OAuth App |
| **GitHub App** (ver seção 4) | Ler PRs, receber webhooks e publicar revisões |
| **GitHub OAuth App** (ver seção 4) | Login dos usuários |
| Assinatura do Claude (plano que inclua o Claude Code) | Análises de IA |
| Docker Engine e Docker Compose V2 | Local e produção |

---

## 2. Configuração (`.env`)

O arquivo `.env` tem os segredos e **nunca** vai para o repositório (já está no `.gitignore`).
Existem dois modelos:
- `.env.example`: para desenvolvimento local.
- `.env.prod.example`: para produção. Cópia no servidor como `.env`, depois preencha.

Campos que **precisam ser trocados** em cada servidor ou instalação nova:

| Variável | O que é | Como obter |
|---|---|---|
| `DOMAIN` | Domínio público, sem `https://` e sem barra | Seu DNS |
| `POSTGRES_PASSWORD` | Senha do banco (use letras e números) | Gere uma |
| `JWT_SECRET_KEY` | Chave de assinatura da sessão, mínimo 32 caracteres | `openssl rand -hex 32` |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | Login com GitHub | OAuth App (seção 4) |
| `GITHUB_OAUTH_REDIRECT_URI` | `https://SEU-DOMINIO/api/v1/auth/github/callback` | Seu domínio |
| `GITHUB_APP_ID` | ID numérico do GitHub App | Página do App |
| `GITHUB_APP_SLUG` | Nome curto do App (aparece em `github.com/apps/<slug>`) | Página do App |
| `GITHUB_APP_PRIVATE_KEY` | Chave privada do App (PEM; `\n` pode ser escapado) | Gerada no App |
| `GITHUB_WEBHOOK_SECRET` | Segredo do webhook (o mesmo configurado no App) | Você escolhe |

Campos importantes para a IA e a sessão:

| Variável | Valor padrão | Observação |
|---|---|---|
| `AI_PROVIDER` | `claude_cli` | `gemini` para usar a API do Gemini (exige `GEMINI_API_KEY`) |
| `CLAUDE_CLI_MODEL` | `claude-sonnet-5-5` | Modelo usado nas análises e revisões |
| `CLAUDE_CLI_COMMAND` | `claude` | Nome do executável do Claude Code |
| `GITHUB_OAUTH_SCOPES` | `read:user user:email read:org` | `read:org` é necessário para vincular membros pela organização |
| `JWT_ACCESS_TOKEN_TTL_MINUTES` | `1440` | Duração da sessão no navegador (máximo 24 horas) |
| `PR_BOT_THREAD_WINDOW_HOURS` | `24` | Por quanto tempo um comentário geral é tratado como conversa com o bot |

> **Atenção:** `GITHUB_APP_SLUG` precisa ser o slug do **seu** App. O bot usa esse nome para ignorar
> os próprios eventos (anti-loop) e para reconhecer menções (`@<slug>`). Se o slug estiver errado, o
> bot pode entrar em loop ou deixar de responder menções.

---

## 3. Desenvolvimento local

### 3.1 Com Docker (recomendado para subir tudo)

```bash
cp .env.example .env        # preencha as credenciais (ver seção 2)
docker compose up -d --build
docker compose exec api alembic upgrade head
```

- Frontend: http://localhost:3000
- API: http://localhost:8000/api/v1/health

**IA no ambiente local:** o compose de desenvolvimento **não monta o login do Claude**. Você tem duas opções:
- **Gemini:** no `.env`, use `AI_PROVIDER=gemini` e preencha `GEMINI_API_KEY`. É a opção mais simples.
- **Claude:** rode o backend fora do Docker (3.2), onde o `claude` do seu computador já está logado.

Sem IA configurada, a plataforma continua funcionando; só as análises e revisões ficam paradas.

### 3.2 Sem Docker (backend direto no seu computador)

Requer Python 3.12 ou 3.14, PostgreSQL com pgvector e Redis em execução.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # Linux/macOS
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# em outro terminal, com o mesmo ambiente:
celery -A app.core.celery_app:celery_app worker --loglevel=INFO --concurrency=1
```

Para usar o Claude localmente, instale o Claude Code, faça o login com `claude auth login` e confira
com `claude auth status` (o campo `"loggedIn"` precisa ser `true`).

### 3.3 Testes

```bash
cd backend
pytest tests/unit                 # não precisa de banco nem de rede
```

Os testes de integração precisam de PostgreSQL com pgvector:

```bash
INTEGRATION_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/banco_de_teste pytest
```

Frontend:

```bash
cd frontend
npm ci
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src
```

---

## 4. Configurar o GitHub

Você precisa criar dois apps, com as URLs do **seu** domínio.

### 4.1 GitHub OAuth App (login dos usuários)

Em **Settings > Developer settings > OAuth Apps**:
- **Homepage URL:** `https://SEU-DOMINIO`
- **Authorization callback URL:** `https://SEU-DOMINIO/api/v1/auth/github/callback`
- Copie o Client ID e gere um Client Secret. Eles vão para o `.env`.
- Se a organização exigir aprovação de apps de terceiros, aprove o OAuth App em
  **Organization settings > Third-party access**. Sem isso, a organização não aparece para os membros
  e o vínculo automático não funciona.

### 4.2 GitHub App (leitura, webhooks e revisões)

Em **Settings > Developer settings > GitHub Apps > New GitHub App**:
- **Webhook URL:** `https://SEU-DOMINIO/api/v1/webhooks/github`
- **Webhook secret:** o mesmo valor de `GITHUB_WEBHOOK_SECRET` no `.env`.
- **Permissões de repositório:**
  - Contents: **Read-only**
  - Metadata: **Read-only**
  - Pull requests: **Read and write** (necessário para publicar revisões e comentários)
- **Eventos (Subscribe to events):**
  - Installation e Installation repositories
  - Pull request
  - Pull request review
  - Pull request review comment
  - **Issue comment** (necessário para a reavaliação por comentário geral)
- Gere a chave privada (`.pem`) e coloque o conteúdo em `GITHUB_APP_PRIVATE_KEY`.
- Instale o App na organização e escolha os repositórios.

> Se você mudar os eventos de um App que já existe, a organização pode precisar aceitar as novas permissões.

---

## 5. Deploy em produção

### 5.1 Primeira instalação

**a) Crie o servidor** (Ubuntu 24.04) e aponte o DNS `A` do domínio para o IP dele.

**b) Acesse o servidor** com a sua chave SSH:

```bash
ssh -i "<CAMINHO-DA-SUA-CHAVE>" root@<IP-DO-SERVIDOR>
```

**c) Rode o script de deploy.** Ele instala o Docker, configura o swap, prepara as pastas do login do
Claude e sobe a stack. Na primeira vez ele para e pede o `.env`:

```bash
export REPO_URL=https://github.com/<SEU-USUARIO>/<SEU-REPO>.git
export APP_DIR=/var/www/pr-insights           # ou o caminho que preferir
curl -fsSL https://raw.githubusercontent.com/<SEU-USUARIO>/<SEU-REPO>/main/scripts/deploy_digitalocean.sh -o /tmp/deploy.sh
sudo -E bash /tmp/deploy.sh
```

Na primeira execução, o script avisa que falta o `.env`. Então:

```bash
cd /var/www/pr-insights
cp .env.prod.example .env
nano .env                    # preencha os campos da seção 2
sudo bash scripts/deploy_digitalocean.sh
```

O script recusa rodar enquanto houver valores de exemplo (`troque`, `seu-dominio`) no `.env`.

**d) Faça o login do Claude no servidor** (interativo, uma única vez):

```bash
ssh -t -i "<CAMINHO-DA-SUA-CHAVE>" root@<IP-DO-SERVIDOR> \
  "cd /var/www/pr-insights && docker compose -f docker-compose.prod.yml exec worker claude auth login"
```

O comando mostra um link. Abra no navegador, autorize e cole o código no terminal. Depois confira:

```bash
docker compose -f docker-compose.prod.yml exec -T worker claude auth status
```

O campo `"loggedIn"` precisa ser `true`. (O código de saída desse comando é sempre 0, então não use o
código de saída para verificar.)

**e) Confira a aplicação:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://SEU-DOMINIO/api/v1/health    # deve ser 200
```

Depois, faça o login pelo navegador com um usuário da organização. O primeiro usuário a instalar o
GitHub App vira o dono (`OWNER`) do tenant.

### 5.2 Atualizar a produção (deploy de uma nova versão)

Cada deploy deve ser aprovado antes. Procedimento:

1. **No seu computador:** rode os testes unitários, faça o commit e envie ao GitHub (`git push origin main`).
2. **No servidor**, confira o estado e atualize o código:
   ```bash
   cd /var/www/pr-insights
   git status                              # deve estar limpo
   git fetch origin main && git merge --ff-only origin/main
   ```
3. **Se a versão mexe no `.env`:** faça backup antes (`cp .env /root/.env.backup-$(date +%F)`) e altere
   só as chaves necessárias, sem imprimir valores de segredo.
4. **Reconstrua e suba a stack:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
   Durante o restart do backend, o proxy pode responder 502 por alguns segundos. É normal.
5. **Se houver migração de banco:**
   ```bash
   docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head
   docker compose -f docker-compose.prod.yml exec -T postgres psql -U ghmgmt -d github_management -c "select version_num from alembic_version;"
   ```
6. **Verifique:** `docker compose -f docker-compose.prod.yml ps` (backend e worker `healthy`), o health
   (`curl https://SEU-DOMINIO/api/v1/health`) e os logs recentes (`logs --since=5m backend worker`). O aviso
   de `SecurityWarning` do worker é esperado, porque ele roda como root.

### 5.3 Volta atrás (rollback)

- Código: no servidor, `git checkout <commit anterior>` e depois `up -d --build` de novo.
- Migração: `alembic downgrade -1` desfaz só a última. Faça isso apenas se a versão anterior do código
  precisar do banco antigo.
- `.env`: restaure o backup e reconstrua a stack.

### 5.4 Cuidados

- **Não apague** `/root/.claude` e `/root/.claude.json`. É o login do Claude. Sem eles, é preciso repetir o login.
- O backend e o worker rodam como root de propósito, para ler esse login.
- O `.env` do servidor **nunca** vai para o repositório.
- Cada deploy que muda o banco, a IA ou o comportamento do webhook deve ser avisado ao time antes.

---

## 6. Operação do dia a dia

| O que fazer | Comando (no servidor, dentro da pasta do projeto) |
|---|---|
| Ver status dos containers | `docker compose -f docker-compose.prod.yml ps` |
| Logs recentes | `docker compose -f docker-compose.prod.yml logs --since=10m backend worker` |
| Ver a fila do Celery | `docker compose -f docker-compose.prod.yml exec -T redis redis-cli llen celery` |
| Conferir a sessão do Claude | `docker compose -f docker-compose.prod.yml exec -T worker claude auth status` |
| Conferir a versão do banco | `docker compose -f docker-compose.prod.yml exec -T postgres psql -U ghmgmt -d github_management -c "select version_num from alembic_version;"` |

Pela tela, em **Configurações > Sistema**, o dono do tenant vê o status da sessão do Claude e renova o login.

---

## 7. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| 502 logo após um deploy | Backend reiniciando | Aguardar alguns segundos e testar o health de novo |
| Fila parada, log com `AUTH_REQUIRED` | Login do Claude expirou | Renovar o login (seção 5.1, passo d, ou pela tela) |
| Análises não aparecem | IA não configurada ou sessão inválida | Conferir `claude auth status` e o `AI_PROVIDER` |
| Membro da organização não é vinculado no login | Falta `read:org` ou o OAuth App não foi aprovado na organização | Ver seção 4.1 |
| Comentário no PR não dispara revisão | Evento `Issue comment` não assinado no App, ou comentário fora das regras | Ver seção 4.2 e a lista de comandos abaixo |
| Bot responde a si mesmo | `GITHUB_APP_SLUG` errado | Corrigir o slug no `.env` e reconstruir a stack |
| Erro 403 em Configurações | Usuário não é dono de nenhum tenant | Comportamento esperado: a seção é restrita a donos |

---

## 8. Revisão automática de PRs: comandos

A plataforma revisa cada PR aberto com as regras da skill da empresa e publica o resultado como comentário
no GitHub. Para pedir uma nova revisão ou falar com o bot, use:

| Como chamar | O que faz |
|---|---|
| `/revisar` (no começo de uma linha) | Nova revisão do PR |
| `/reavaliar` (no começo de uma linha) | Mesmo efeito de `/revisar` |
| `@<slug-do-app>` ou `@pr-insights` no texto | Nova revisão, com resposta na conversa |
| Comentário geral logo depois de uma resposta do bot (até 24 horas) | Nova revisão, sem precisar de menção |
| Resposta a um comentário em linha que o bot publicou | Nova revisão |
| Novo push no PR | Nova revisão |

Regras:
- O comando só vale no começo de uma linha: `/revisar` no meio de uma frase não dispara.
- Não diferencia maiúsculas: `/REVISAR` funciona.
- Comentários do próprio bot são ignorados.
- Entre duas revisões do mesmo PR há um intervalo mínimo de 180 segundos. Um gatilho dentro desse intervalo é descartado.

As regras das revisões ficam em `backend/app/review_skills/git_code_review/rules/` e podem ser editadas
pelo dono do tenant em **Configurações > Revisão de PRs**.

---

## 9. Estrutura do repositório

| Pasta | Conteúdo |
|---|---|
| `backend/` | API FastAPI, workers Celery, migrações Alembic, testes |
| `frontend/` | Next.js (App Router), Tailwind e componentes no padrão shadcn |
| `deploy/` | Configuração do Caddy (HTTPS automático) |
| `scripts/` | Script de deploy (`deploy_digitalocean.sh`) |
| `docker-compose.yml` | Ambiente de desenvolvimento |
| `docker-compose.prod.yml` | Stack de produção (com limites de memória) |
| `.env.example` / `.env.prod.example` | Modelos de configuração (sem segredos) |
