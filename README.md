# PR Insights — Gestão de Pull Requests com IA

Plataforma multi-tenant que importa Pull Requests do GitHub, calcula métricas de engenharia
(tamanho, tempo até o merge) e gera análises com IA (resumo, categoria, risco, parecer de produto).

## Deploy em produção (DigitalOcean Droplet, Ubuntu 24.04)

**1. Crie o Droplet** com Ubuntu 24.04 (recomendado: 4 GB de RAM). Anote o IP.

**2. Aponte o domínio:** crie um registro DNS `A` do seu domínio para o IP do Droplet.

**3. Coloque o projeto no GitHub** (repositório git com este código).

**4. No Droplet, rode o deploy:**

```bash
# Conecte-se ao Droplet e execute (troque a URL pelo seu repositório):
export REPO_URL=https://github.com/SEU-USUARIO/SEU-REPO.git
sudo -E bash -c 'curl -fsSL https://raw.githubusercontent.com/SEU-USUARIO/SEU-REPO/main/scripts/deploy_digitalocean.sh | bash'
```

Na primeira execução o script para e pede o `.env`, porque ele tem os segredos. Então:

```bash
cd /opt/github-management
cp .env.prod.example .env
nano .env        # preencha DOMAIN e os campos vazios
sudo bash scripts/deploy_digitalocean.sh
```

O script configura o swap de 4 GB, instala o Docker, sobe a stack, aplica as migrações e baixa os
modelos locais definidos no `.env`. Ele pode ser executado de novo para atualizar a aplicação.

**5. Configure o GitHub** com o seu domínio:
- **GitHub OAuth App** — callback: `https://SEU-DOMINIO/api/v1/auth/github/callback`
- **GitHub App** — webhook: `https://SEU-DOMINIO/api/v1/webhooks/github`

### Limitação de hardware

A IA usa o Claude Code CLI (`AI_PROVIDER=claude_cli`), autenticado com a assinatura do Claude e não com
chave de API. O login fica salvo no host (`/root/.claude` e `/root/.claude.json`) e é reaproveitado pelo
backend e pelo worker. Se a sessão expirar, a fila pausa (`AUTH_REQUIRED`) sem descartar PRs; a renovação
é feita em Configurações > Sistema, ou no servidor com `claude auth login`. Para usar o Gemini, troque para
`AI_PROVIDER=gemini` e preencha `GEMINI_API_KEY`.

## Desenvolvimento local

```bash
cp .env.example .env          # preencha as credenciais (ver comentários no arquivo)
docker compose up -d --build
docker compose exec api alembic upgrade head
```

- Frontend: http://localhost:3000
- API: http://localhost:8000/api/v1/health
- Testes do backend (requer PostgreSQL com pgvector):

```bash
cd backend
pip install -r requirements-dev.txt
INTEGRATION_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/banco_de_teste pytest
```

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `backend/` | API FastAPI, workers Celery, migrações Alembic, testes |
| `frontend/` | Next.js (App Router), Tailwind e componentes no padrão shadcn |
| `deploy/` | Configuração do Caddy (HTTPS automático) |
| `scripts/` | Script de deploy para o DigitalOcean |
| `docker-compose.yml` | Ambiente de desenvolvimento |
| `docker-compose.prod.yml` | Stack de produção (com limites de memória) |
