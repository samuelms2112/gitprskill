# Especificação Técnica e Arquitetural: Plataforma de Gestão do GitHub, Relatórios de PRs e Kanban com IA

A evolução da engenharia de software moderna exige visibilidade contínua sobre a velocidade de entrega, a qualidade das revisões de código e a rastreabilidade entre demandas de negócio e código-fonte. Esta especificação técnica estabelece a arquitetura e o plano de implementação de uma plataforma self-hosted para gestão de repositórios do GitHub, análise avançada de Pull Requests (PRs) e gerenciamento de tarefas no estilo Kanban (Jira/Trello), impulsionada por modelos de Inteligência Artificial como o Google Gemini.

O desenvolvimento do sistema está estruturado em uma abordagem progressiva por fases. A **Fase 1 (MVP)** foca na ingestão de dados de repositórios do GitHub, captura de eventos em tempo real, cálculo de métricas de engenharia e geração de relatórios de Pull Requests mergeados nas branches principais. As **Fases 2 e 3** expandem o ecossistema com a inclusão do quadro Kanban interativo, sincronização bidirecional de estado e automações de código com IA.

---

## 1. Visão Geral e Arquitetura do Sistema

A arquitetura do sistema foi projetada sob o paradigma self-hosted e modular, inspirando-se nos padrões estabelecidos pelo repositório acadêmico e plataforma RAISE (Repository Analysis in Software Engineering). A infraestrutura utiliza contêineres Docker para garantir reprodutibilidade, isolamento de componentes e fácil implantação em servidores locais ou nuvens privadas.

O ecossistema é composto por quatro camadas fundamentais:
* **Camada de Apresentação (Frontend)**: Interface web responsiva desenvolvida em React com o framework Next.js e TypeScript, oferecendo dashboards analíticos, visualização de cartões Kanban e tabelas interativas de dados.
* **Camada de Serviços (Backend API)**: API RESTful construída em Python (utilizando FastAPI ou Django), responsável pela validação de requisições, orquestração de tarefas, autenticação e regras de negócio.
* **Camada de Processamento Assíncrono**: Um agente de enfileiramento baseado em Redis Broker e trabalhadores Celery (Celery Workers) para executar a mineração de dados, sincronização de repositórios e chamadas à API da IA em segundo plano sem bloquear a interface do usuário.
* **Camada de Persistência (Banco de Dados)**: Banco de dados relacional PostgreSQL com um esquema fortemente tipado e normalizado, otimizado para consultas analíticas e rastreabilidade entre artefatos de código e planejamento.

O fluxo de dados entre as fases da plataforma garante uma transição suave da coleta de métricas técnicas de PRs até a gestão completa de tarefas de desenvolvimento.

### Tabela 1.1: Matriz de Evolução por Fases do Projeto

A tabela a seguir compara o escopo e os componentes técnicos entregues ao longo da evolução da plataforma.

| Dimensão Arquitetural | Fase 1: MVP (Relatórios & Analytics de PRs) | Fase 2: Kanban Bidirecional (Estilo Kaneo/Jira) | Fase 3: Automação Inteligente com IA |
| --- | --- | --- | --- |
| **Foco Principal** | Visibilidade e relatórios de PRs mergeados nas branches `main`/`master` | Quadro Kanban interativo com gestão de demandas e sync de issues | Automação de revisão de código, Conventional Commits e Release Notes |
| **Ingestão do GitHub** | REST API Search (`/search/issues`) e Webhooks (`pull_request.closed`) | GitHub App com escuta de Webhooks para branches, issues e PRs | Análise de diffs de código e históricos de alterações |
| **Modelo de Dados** | Tabelas de Repositórios, Autores, PRs, Revisões e Arquivos | Tabelas de Quadros, Colunas, Tarefas, Labels e Mapeamento de Status | Registro de Execuções de IA, Prompts, Summaries e Métricas de Uso |
| **Integração de IA** | Classificação de impacto e geração de resumos básicos de PRs | Movimentação automática de tarefas com base em análise semântica | Integração com Gemini 2.5 Flash (`gcm.js`) e Gemini Code Assist |
| **Visualização** | Dashboards de métricas (Chart.js), tabelas filtráveis e exportação CSV/JSON | Quadro de cartões arrastáveis (Drag & Drop), visão de lista e detalhes | Comentários automatizados nos PRs e painéis de insights preditivos |

---

## 2. Estratégia de Coleta e Ingestão de Dados do GitHub

Para manter o banco de dados atualizado sem exceder os limites de requisições (Rate Limits) da API do GitHub, o sistema emprega uma estratégia híbrida de ingestão: carga histórica via REST Search API e sincronização em tempo real via Webhooks.

### 2.1. Ingestão Histórica via GitHub REST Search API
Durante a inicialização de um novo repositório na plataforma, o sistema executa um carregamento inicial para recuperar o histórico de contribuições. Conforme documentado em práticas de integração com a API REST do GitHub, a maneira mais eficiente de recuperar todos os Pull Requests mergeados de um usuário ou organização cruzando repositórios é utilizar o endpoint unificado de busca de issues:

`GET /search/issues?q=org:<organizacao>+type:pr+is:merged`

Como o GitHub trata os Pull Requests internamente como um tipo especial de issue, esse endpoint permite filtrar exatamente as contribuições integradas sem a necessidade de varrer individualmente cada repositório. Para repositórios específicos, a API de Pull Requests padrão é consultada:

`GET /repos/{owner}/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100`

### 2.2. Captura em Tempo Real via Webhooks
Após a carga inicial, a plataforma passa a escutar os eventos transmitidos pelos Webhooks do GitHub. Conforme a documentação oficial de Webhooks, essa abordagem elimina a necessidade de requisições periódicas contínuas, reduz o consumo de infraestrutura e viabiliza atualizações em tempo quase real.

O servidor webhook ouve requisições na rota `/api/v1/webhooks/github` e processa os seguintes eventos primários:
* `pull_request`: Disparado ao abrir, fechar, reabrir ou atualizar um PR. O sistema filtra os dados de fechamento onde a integração foi concluída para registrar o merge na branch de destino (`main`, `master`, `master-tip`).
* `pull_request_review`: Captura aprovações (`APPROVED`), pedidos de alteração (`CHANGES_REQUESTED`) e comentários de revisores.
* `push`: Monitora alterações diretas nas branches rastreadas para atualizar os marcadores de commits principais.

### 2.3. Autenticação e Gestão de Limites de Requisições
Para suportar o volume de requisições exigido pela mineração de repositórios, a plataforma suporta dois métodos de autenticação:
1. **Tokens de Acesso Pessoal (Personal Access Tokens)**: Utilizados em instalações simplificadas, com escopos de leitura para repositórios e organização.
2. **GitHub App**: Método recomendado para a Fase 2. A plataforma registra uma aplicação própria no GitHub com permissões granulares de API, elevando a capacidade de requisições por hora.

O cliente de API construído no backend intercepta os cabeçalhos de limite de requisições fornecidos pelo GitHub. Caso a cota restante esteja próxima do limite, o trabalhador Celery entra em pausa automática até que o período de renovação seja atingido, garantindo a estabilidade da coleta.

---

## 3. Modelo de Dados Relacional (PostgreSQL)

O esquema do banco de dados relacional PostgreSQL foi estruturado sob princípios de normalização avançada, garantindo integridade referencial e alta performance em consultas de agregação. O modelo estende os conceitos demonstrados no ecossistema RAISE, separando o contexto técnico do Git do contexto de planejamento do Kanban.

### 3.1. Esquema DDL do Banco de Dados (SQL)

O código SQL a seguir define a estrutura de tabelas essenciais para a Fase 1 e a integração com a Fase 2:

```sql
-- Tabela de Repositórios Rastreados
CREATE TABLE repositories (
    id BIGINT PRIMARY KEY,
    github_id BIGINT UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    owner_login VARCHAR(150) NOT NULL,
    html_url TEXT NOT NULL,
    default_branch VARCHAR(100) DEFAULT 'main',
    is_private BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Contribuidores / Usuários
CREATE TABLE contributors (
    id SERIAL PRIMARY KEY,
    github_id BIGINT UNIQUE NOT NULL,
    login VARCHAR(150) NOT NULL,
    avatar_url TEXT,
    html_url TEXT,
    name VARCHAR(255),
    email VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabela Principal de Pull Requests
CREATE TABLE pull_requests (
    id SERIAL PRIMARY KEY,
    github_pr_id BIGINT UNIQUE NOT NULL,
    repository_id BIGINT NOT NULL REFERENCES repositories(github_id) ON DELETE CASCADE,
    number INT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    state VARCHAR(50) NOT NULL,
    is_merged BOOLEAN DEFAULT false,
    author_id BIGINT NOT NULL REFERENCES contributors(github_id),
    head_branch VARCHAR(255) NOT NULL,
    base_branch VARCHAR(255) NOT NULL,
    additions INT DEFAULT 0,
    deletions INT DEFAULT 0,
    changed_files INT DEFAULT 0,
    pr_size_category VARCHAR(10) CHECK (pr_size_category IN ('XS', 'S', 'M', 'L', 'XL')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    closed_at TIMESTAMP WITH TIME ZONE,
    merged_at TIMESTAMP WITH TIME ZONE,
    time_to_merge_seconds BIGINT,
    html_url TEXT NOT NULL,
    CONSTRAINT uq_repo_pr_number UNIQUE (repository_id, number)
);

-- Tabela de Revisões de PR (Reviews & Approvers)
CREATE TABLE pr_reviews (
    id SERIAL PRIMARY KEY,
    github_review_id BIGINT UNIQUE NOT NULL,
    pull_request_id INT NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    reviewer_id BIGINT NOT NULL REFERENCES contributors(github_id),
    state VARCHAR(50) NOT NULL, -- APPROVED, CHANGES_REQUESTED, COMMENTED
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    body TEXT
);

-- Tabela de Tarefas do Kanban (Fase 2 - Preparada para Integração)
CREATE TABLE kanban_tasks (
    id SERIAL PRIMARY KEY,
    task_key VARCHAR(50) UNIQUE NOT NULL, -- Ex: PROJ-101
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'backlog', -- backlog, in_progress, in_review, done
    priority VARCHAR(20) DEFAULT 'medium',
    assignee_id INT REFERENCES contributors(id),
    linked_pull_request_id INT REFERENCES pull_requests(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices de Otimização para Consultas de Relatórios
CREATE INDEX idx_pr_merged_at ON pull_requests(merged_at) WHERE is_merged = true;
CREATE INDEX idx_pr_base_branch ON pull_requests(base_branch);
CREATE INDEX idx_pr_author ON pull_requests(author_id);
CREATE INDEX idx_reviews_pr ON pr_reviews(pull_request_id);
```

---

## 4. Motor de Métricas e Analytics de Pull Requests

Para transformar dados brutos de commits e merges em relatórios de engenharia acionáveis, a plataforma implementa um motor dedicado de cálculo de métricas (PR Metrics Engine), baseado no guia de automação de relatórios de Pull Requests.

### 4.1. Categorização por Tamanho de PR (PR Sizing)
O volume de código alterado em um PR correlaciona-se diretamente com o tempo necessário para revisão. O sistema calcula a soma total de modificações (`linhas adicionadas + linhas removidas`) e classifica cada PR segundo a escala padrão da indústria:

```python
def calculate_pr_size(additions: int, deletions: int) -> tuple[str, str]:
    total_changes = additions + deletions
    if total_changes <= 10:
        return ("XS", "#c0e0c0")  # Verde Claro
    elif total_changes <= 50:
        return ("S", "#b0d0b0")   # Verde
    elif total_changes <= 250:
        return ("M", "#f0e0b0")   # Amarelo Claro
    elif total_changes <= 1000:
        return ("L", "#f0c0a0")   # Laranja Claro
    else:
        return ("XL", "#f0a0a0")  # Vermelho Claro
```

### 4.2. Cálculo de Lead Time e Tempo de Merge (Time-to-Merge)
O tempo decorrido desde a abertura de um PR até a sua integração efetiva na branch principal (`main`/`master`) é calculado em segundos e formatado em intervalos legíveis (`dias, horas, minutos`):

$$\text{Time-to-Merge} = \text{merged\_at} - \text{created\_at}$$

Esse indicador permite identificar gargalos na fase de Code Review e isolar PRs com longos períodos de inatividade.

### 4.3. Mapeamento de Revisores e Aprovadores
Através do cruzamento da tabela `pr_reviews`, o motor extrai apenas os revisores únicos cujo estado final foi registrado como `APPROVED`. Essa contagem diferencia comentários informativos de aprovações formais de arquitetura.

### 4.4. Visualização e Exportação dos Relatórios
Os dados processados são apresentados em três formatos no frontend:
* **Dashboard Interativo em HTML/React**: Gráficos dinâmicos (Chart.js ou Plotly) exibindo a distribuição de tamanhos de PR, vazão de merges por autor e tempo médio de revisão por repositório.
* **Filtros Dinâmicos por Interface**: Filtros em tempo real por intervalo de datas, repositório alvo, autor da solicitação e branch de destino.
* **Exportação Multiformato**: Geração de arquivos estruturados em CSV e JSON para consumo por equipes de BI ou relatórios executivos de entregas.

---

## 5. Automações e Inteligência Artificial com Google Gemini

A integração da Inteligência Artificial Generativa atua como um catalisador de produtividade na plataforma, automatizando tarefas repetitivas de documentação e revisão de código. O modelo escolhido como padrão é o **Google Gemini 2.5 Flash**, devido ao seu baixo custo por token, janela de contexto ampliada e latência de resposta reduzida para análises de código.

### 5.1. Automação de Conventional Commits e PR Descriptions (`gcm.js`)
Inspirado na arquitetura da ferramenta CLI `gcm.js`, a plataforma oferece um serviço interno que lê o *diff* de alterações e gera automaticamente mensagens padronizadas no formato Conventional Commits (`type(scope): description`), além de nomes sugestivos para branches e descrições estruturadas para o PR.

O fluxo de processamento inclui um estágio de amostragem inteligente de *diffs* para lidar com grandes volumes de código:

```javascript
// Conceito de prompt enviado ao Gemini 2.5 Flash para geração de documentação
const prompt = `
Você é um engenheiro especialista em Git. Analise o diff de código abaixo e gere:
1. Uma mensagem de commit no formato Conventional Commits (ex: feat(auth): add OAuth2 provider).
2. Uma sugestão de nome de branch limpa (ex: feature/oauth2-provider).
3. Uma descrição detalhada do PR dividida em: "O que mudou", "Por que mudou" e "Como testar".

Diff de Alterações:
${summarizedDiff}
`;
```

### 5.2. Geração Automática de Release Notes
Ao final de cada ciclo de entrega ou sprint, a plataforma utiliza o Gemini para compilar todos os PRs mergeados nas branches `main` ou `master-tip` dentro do período e produzir um resumo executivo de notas de lançamento (Release Notes) em linguagem natural, categorizando as entregas por *Novas Funcionalidades*, *Correções de Bugs*, *Melhorias de Performance* e *Alterações Críticas*.

### 5.3. Revisão Automatizada de Código (Gemini Code Assist)
Alinhado com os padrões do Gemini Code Assist em repositórios do GitHub, a plataforma permite configurar um assistente automatizado de code review. O assistente analisa o título, a descrição e o conteúdo dos arquivos alterados no PR, inserindo comentários instruídos sobre boas práticas, clareza e conformidade com o guia de estilo do projeto.

---

## 6. Evolução para Kanban Bidirecional estilo Jira/Trello (Fase 2 & 3)

Com a infraestrutura de relatórios de PRs operacional na Fase 1, a plataforma evolui para um ambiente completo de gestão de projetos. O modelo de dados estendido conecta cartões Kanban a issues e Pull Requests do GitHub com sincronização bidirecional em tempo real, baseando-se no funcionamento do sistema **Kaneo** e na flexibilidade do **Trello e Jira**.

### 6.1. Regras de Sincronização Bidirecional de Estado
A sincronização garante que a atividade diária do desenvolvedor no terminal ou na interface do GitHub reflita instantaneamente no quadro do projeto:

1. **Criação de Tarefa ➔ GitHub Issue**: Ao criar um cartão no Kanban da plataforma, o sistema abre automaticamente uma issue correspondente no repositório vinculado, sincronizando título, descrição, prioridade e tags.
2. **Push de Branch ➔ Estado 'Em Progresso'**: Quando o desenvolvedor cria e envia uma branch seguindo o padrão da tarefa (ex: `feature/PROJ-101-login-screen`), o webhook da plataforma captura a alteração e move o cartão para a coluna *In Progress*.
3. **Abertura de PR ➔ Estado 'Em Revisão'**: Ao abrir um Pull Request contendo a chave da tarefa ou a instrução `Closes #101` no título ou corpo, a plataforma vincula o PR ao cartão e o move para a coluna *In Review*.
4. **Merge de PR ➔ Estado 'Concluído'**: O evento de merge do PR na branch `main` encerra automaticamente a issue vinculada no GitHub e move o cartão do Kanban para a coluna *Done*.

### 6.2. Estrutura de Integração Híbrida (Jira Lists & Smart Links)
Seguindo os padrões de interoperabilidade entre Trello e Jira, o sistema suporta visões flexíveis:
* **Visão de Lista Dinâmica**: Permite filtrar tarefas por sprint, responsável ou rótulo.
* **Vínculos Inteligentes (Smart Links)**: Exibe previews enriquecidos de PRs, branches e commits diretamente dentro dos detalhes do cartão Kanban.

---

## 7. Roteiro Prático de Implementação (Roadmap de Execução)

Para viabilizar a construção do sistema por uma equipe de desenvolvimento, a tabela a seguir detalha o roteiro de execução em etapas sequenciais.

### Tabela 7.1: Plano de Ação para Implementação do MVP (Fase 1)

| Etapa | Componente | Tarefas Técnicas de Implementação | Entregável Esperado |
| --- | --- | --- | --- |
| **Passo 1** | Ambiente & Banco de Dados | Configurar contêineres Docker (PostgreSQL, Redis) e executar os scripts DDL de criação das tabelas `repositories`, `contributors`, `pull_requests` e `pr_reviews`. | Ambiente de banco de dados relacional funcional e isolado. |
| **Passo 2** | Cliente da API do GitHub | Desenvolver o cliente HTTP em Python com suporte a autenticação, controle de paginação e rotina de tratamento de limite de requisições. | Módulo Python capaz de autenticar e buscar repositórios e PRs sem falhas de quota. |
| **Passo 3** | Ingestão Histórica & Webhooks | Implementar a rota `/search/issues` para carga inicial e criar o endpoint de recepção de Webhooks (`/api/v1/webhooks/github`). | Banco de dados populado com histórico e recebendo atualizações de merge en tempo real. |
| **Passo 4** | Motor de Analytics de PRs | Escrever as funções de cálculo para categorias de tamanho de PR (XS a XL), tempo até o merge (Lead Time) e consolidação de revisores aprovadores. | Funções de métricas validadas com testes unitários. |
| **Passo 5** | Dashboard & Exportação | Criar a interface em React/Next.js com gráficos interativos (Chart.js), tabela com filtros por data/autor/repo e botões de exportação CSV/JSON. | Interface web completa para visualização de relatórios de PRs. |
| **Passo 6** | Camada de IA (Gemini) | Integrar a API do Gemini 2.5 Flash para geração de resumos de PRs e Release Notes automatizados. | Serviço de IA gerando relatórios executivos de entregas em linguagem natural. |

---

Com a conclusão do Passo 6, o MVP da Fase 1 estará totalmente operacional, fornecendo um sistema robusto de inteligência sobre Pull Requests e estabelecendo os alicerces técnicos necessários para a ativação do quadro Kanban bidirecional na Fase 2.
