# Lab 03: Mineração de métricas DORA

Pipeline inicial da Sprint 01 para coletar dados públicos de repositórios GitHub
e calcular as métricas DORA como proxies. A especificação completa está em
[guide/03 - Mineração de Métricas DORA.md](guide/03%20-%20Minera%C3%A7%C3%A3o%20de%20M%C3%A9tricas%20DORA.md).

## Arquitetura

```text
pipeline/__main__.py       CLI e comando único
pipeline/config.py         configuração TOML e caminhos
pipeline/github_client.py  REST próprio, cache, paginação, retries e rate limit
pipeline/collector.py      candidatos, metadados, releases, runs e funil
pipeline/metrics.py        funções puras testáveis das métricas DORA
tests/                     fixtures e testes sem chamadas à API
```

O cliente usa apenas a biblioteca padrão para acessar a API. Nenhuma biblioteca
pronta de acesso ao GitHub é usada.

## Executar a coleta

### 1. Instalar as dependências

Na raiz do projeto, execute:

```bash
python -m pip install -e ".[dev]"
```

### 2. Configurar o token do GitHub

Crie um arquivo local chamado `.env` com o token do GitHub:

```env
GITHUB_TOKEN=seu_token_do_github
```

O arquivo `.env` é ignorado pelo Git. Nunca coloque o token no `README`, em
`config.toml` ou em arquivos commitados.

Carregue o token no terminal atual:

```bash
set -a
source .env
set +a
```

### 3. Criar a configuração da coleta

```bash
cp config.toml.example config.toml
```

Abra `config.toml` e substitua `start_date` e `end_date` pela janela de 12 meses
definida pelo professor. Para o primeiro teste, use:

```toml
max_repositories = 2
```

### 4. Fazer a primeira coleta

```bash
python -m pipeline --config config.toml
```

Esse comando busca candidatos com mais de 1.000 estrelas e coleta, para cada
repositório, workflows, releases publicadas e workflow runs de `push` no
default branch.

### 5. Conferir os resultados

Os arquivos são gravados em:

```text
data/raw/*.json     dados organizados por repositório
data/raw/funnel.csv  funil de seleção
data/cache/*.json   respostas originais da API
```

O funil informa quantos candidatos possuem Actions e quantos atendem ao mínimo
de 5 releases e 50 workflow runs válidos.

### 6. Executar com 100 repositórios

Depois de conferir a primeira execução, altere em `config.toml`:

```toml
max_repositories = 100
```

Execute novamente:

```bash
python -m pipeline --config config.toml
```

O cache em `data/cache/` permite retomar a coleta após interrupção sem repetir
respostas já obtidas. Para interromper com segurança, use `Ctrl+C` e execute o
mesmo comando novamente depois.

Para testar sem consumir a API:

```bash
pytest --cov=pipeline.metrics --cov-report=term-missing
```

## Sprint 01

Esta base implementa a coleta de candidatos, workflows, releases publicadas e
workflow runs de `push` no default branch, além do filtro mínimo de 5 releases e
50 runs válidos. A coleta de commits entre releases e a consolidação das métricas
por repositório serão as próximas fatias da sprint.
