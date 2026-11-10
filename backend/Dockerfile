# Imagem da API FastAPI e do worker Celery (a mesma imagem, dois comandos).

# Estágio auxiliar: Node.js 22 com o Claude Code CLI, na versão fixada abaixo.
# O CLI exige Node 22 ou superior; o apt do Debian traz uma versão antiga, por isso vem da imagem oficial.
FROM node:22-bookworm-slim AS claude-cli
ARG CLAUDE_CODE_VERSION=2.1.321
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && npm cache clean --force

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Node.js e o Claude Code CLI, copiados do estágio acima. ``libstdc++6`` é a dependência do binário do Node.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=claude-cli /usr/local/ /usr/local/

# Usuário sem privilégios para executar a aplicação.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

# Instala dependências antes do código para aproveitar o cache de camadas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
