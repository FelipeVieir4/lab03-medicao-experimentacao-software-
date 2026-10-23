# Lab 03: Mineração de métricas DORA

Pipeline reprodutível que seleciona repositórios populares do GitHub que usam
GitHub Actions, coleta releases, commits entre releases, workflow runs e tags, e
calcula as métricas DORA como proxies. A especificação completa está em
[guide/03 - Mineração de Métricas DORA.md](guide/03%20-%20Minera%C3%A7%C3%A3o%20de%20M%C3%A9tricas%20DORA.md).

## Arquitetura

```text
pipeline/__main__.py       CLI: comando único (coleta + dataset)
pipeline/config.py         configuração TOML
pipeline/github_client.py  cliente REST/GraphQL próprio: cache SQLite, paginação por Link,
                           rate limit, backoff exponencial e rodízio de tokens
pipeline/collector.py      busca fatiada, funil de seleção e coleta por repositório
pipeline/dataset.py        consolida os JSONs em CSVs e calcula as métricas
pipeline/metrics.py        funções puras das métricas DORA
analysis/descritivas.py    estatística descritiva das RQs 01-04 e classificação DORA (C1)
analysis/correlacoes.py    RQ 05: Spearman entre deployment frequency e CFR (a) e (b)
analysis/fatores.py        RQ 06: Kruskal-Wallis/Mann-Whitney por fator, Holm, ε² e Cliff's delta
analysis/sensibilidade.py  RQ 07: classificação em C1, C2 e C3, % de mudança e kappa ponderado
analysis/rotular.py        amostra-ouro: ferramenta interativa de rotulação
analysis/concordancia.py   amostra-ouro: kappa de Fleiss e rótulo de consenso
analysis/heuristica.py     amostra-ouro: precisão, recall e F1 da heurística de release corretiva
analysis/rework.py         RQ 08 (bônus): rework rate e comparação com o CFR (b)
docs/protocolo-rotulagem.md  como rotular, protocolo de desempate e refinamento da heurística
tests/                     testes com fixtures, sem chamadas à API
docs/dicionario-de-dados.md  documentação de cada coluna dos CSVs
docs/decisoes-metodologicas.md  decisões da coleta e seus efeitos (base da Metodologia)
```

Só a biblioteca padrão do Python acessa a API. Nenhuma biblioteca pronta de
acesso ao GitHub é usada.

## Executar

Requer Python 3.10 ou superior.

### 1. Instalar

```bash
python -m pip install -e ".[dev]"
```

### 2. Token do GitHub

Crie um arquivo `.env` na raiz do projeto (ele é ignorado pelo Git):

```env
GITHUB_TOKEN=seu_token
```

Um token clássico sem escopos basta (só dados públicos). Com mais de um token, a
coleta alterna entre eles e fica mais rápida:

```env
GITHUB_TOKENS=token1,token2,token3
```

O pipeline lê o `.env` sozinho. Também aceita a variável de ambiente já definida
no terminal.

### 3. Configuração

```bash
cp config.toml.example config.toml        # Windows: copy config.toml.example config.toml
```

A janela padrão é 2025-10-02 a 2026-10-01. A coleta para quando encontra
`target_sample` repositórios elegíveis (padrão 350; o guia exige ao menos 300).
Para um teste rápido, use `target_sample = 2` e `batch_size = 5`.

### 4. Rodar (comando único)

```bash
python -m pipeline --config config.toml
```

O comando faz a coleta e depois gera o dataset. Também é possível rodar as
etapas separadamente: `--step collect` ou `--step dataset` (este último só lê os
arquivos locais e não usa a API).

**Retomada:** toda resposta da API é gravada em `data/cache/github_cache.sqlite`
no momento em que chega. Se a coleta parar (rate limit, queda de rede, `Ctrl+C`,
computador desligado), basta rodar o mesmo comando: o que já foi baixado vem do
cache e a coleta continua de onde parou.

**Rate limit:** o cliente lê `X-RateLimit-Remaining`/`X-RateLimit-Reset` e
espera sozinho quando a cota acaba; erros 5xx e de rede são repetidos com
backoff exponencial (1 s, 2 s, 4 s, ...).

**Vários tokens:** para acrescentar um token no meio da coleta, interrompa com
`Ctrl+C`, edite o `GITHUB_TOKENS` no `.env` e rode o mesmo comando de novo.

### 5. Saídas

```text
data/raw/funnel.csv            funil de seleção (tabela da Metodologia)
data/raw/screening.csv         situação de cada candidato avaliado
data/raw/repos/*.json          dados brutos de cada repositório elegível
data/raw/execution_log.csv     métricas de cada execução (tempo, chamadas por token, esperas, speedup)
data/raw/token_events.csv      trocas e esgotamentos de token
data/raw/collect.log           log completo
data/processed/*.csv           dataset final e métricas (ver docs/dicionario-de-dados.md)
data/processed/gold_sample_template.csv  amostra-ouro sorteada (seed 42) para rotulagem
data/gold/rotulos_<avaliador>.csv         planilha de rotulagem de cada avaliador
```

Os arquivos grandes não vão para o Git: o cache (`data/cache/`, ~1,5 GB), os JSONs
brutos (`data/raw/repos/`, ~1,5 GB) e `release_commits.csv.gz` (~190 MB). Eles são
regenerados pelo pipeline. `workflow_runs.csv.gz` (~30 MB) é versionado compactado.

## Análises

As análises leem só `data/processed/repositories_metrics.csv` (sem API) e podem ser
reexecutadas sempre que o dataset for recalculado.

```bash
pip install -e ".[analysis]"
python -m analysis.descritivas
python -m analysis.correlacoes
python -m analysis.fatores
python -m analysis.sensibilidade
python -m analysis.rework
```

RQs 01 a 04: mediana e IQR das métricas, classificação DORA em C1 e proporção de
censura. Saída em `reports/resultados/rq01_04/` (`descritivas.csv`,
`classificacao_c1.csv`, `censura.csv` e as tabelas prontas em `rq01_04.md`).

RQ 05: correlação de Spearman entre deployment frequency e CFR, separada para as
variantes (a) e (b), com ρ, p-valor e n. Saída em `reports/resultados/rq05/`
(`spearman.csv`, `dispersao.png` com eixo x em escala log e `rq05.md`). O teste é
implementado com a biblioteca padrão (postos com média nos empates e teste t com
n − 2 g.l., o mesmo método do `scipy.stats.spearmanr`); só os gráficos usam matplotlib.

RQ 06: para cada fator (linguagem principal, quartis de estrelas, de contribuidores e de
idade e, quando existir `data/gold/consenso.csv`, tipo do projeto) × métrica de C1, teste de
Kruskal-Wallis (ou Mann-Whitney com dois grupos), p-valores corrigidos por Holm, ε² e Cliff's
delta; nos testes significativos, comparações par a par. Saída em `reports/resultados/rq06/`
(`testes.csv`, `posthoc.csv`, `medianas.csv`, `efeitos.png` e `rq06.md`). Implementado com a
biblioteca padrão e conferido com `scipy.stats` e `statsmodels`.

RQ 07: classificação DORA de cada repositório nas combinações C1, C2 e C3, % de repositórios
que mudam de categoria e kappa de Cohen com ponderação linear para cada par, na classificação
geral e em cada métrica. Saída em `reports/resultados/rq07/` (`classes.csv`, `pares.csv`,
`distribuicao.csv`, `transicoes.csv`, `distribuicao.png` e `rq07.md`).

RQ 08 (bônus): mediana e IQR do rework rate (releases corretivas / releases), comparação
com o CFR (b) e Spearman entre os dois. Saída em `reports/resultados/rq08/` (`rework.csv`,
`rework.png` e `rq08.md`).

### Validação manual (amostra-ouro)

Cada avaliador preenche `data/gold/rotulos_<usuario>.csv`, à mão ou com a ferramenta
interativa (valores aceitos e critérios em `docs/protocolo-rotulagem.md`):

```bash
python -m analysis.rotular --avaliador <usuario>
```

Depois que todos terminarem:

```bash
python -m analysis.concordancia
python -m analysis.heuristica
```

O primeiro calcula o kappa de Fleiss das três dimensões, gera `data/gold/consenso.csv` e
lista em `data/gold/divergencias.csv` os casos sem maioria. Depois da reunião, preencha a
coluna `decisao` e rode o comando de novo. O segundo compara cada versão da heurística com
o consenso (precisão, recall e F1, meta F1 ≥ 0,70). Os resultados ficam em
`reports/resultados/validacao/`.

## Como a seleção economiza cota

Cada candidato passa pelas etapas mais baratas primeiro e só segue se for
aprovado: workflows (1 chamada) → releases na janela → contagem de runs (1
chamada) → runs completos mês a mês → para os elegíveis, `compare` entre
releases, tags (GraphQL) e contribuidores. A busca de candidatos é fatiada por
faixas de estrelas porque a API devolve no máximo 1.000 resultados por consulta,
e os runs são buscados mês a mês. Meses que passam de 1.000 resultados só são
subdivididos com `split_capped_runs = true`; no padrão (`false`), entram os 1.000 runs
mais recentes do mês e o mês fica registrado em `runs_capped_days`.

## Testes

```bash
pytest --cov=pipeline.metrics --cov-report=term-missing
```
