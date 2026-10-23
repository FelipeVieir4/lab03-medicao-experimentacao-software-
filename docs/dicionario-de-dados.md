# Dicionário de dados

Todos os arquivos são gerados por `python -m pipeline --config config.toml`.
Datas em ISO 8601 (UTC). Janela de observação: **2025-10-02 a 2026-10-01**.

## data/raw/funnel.csv: funil de seleção

| Coluna | Tipo | Descrição |
|---|---|---|
| stage | texto | `candidates`, `with_actions`, `min_releases`, `eligible` |
| description | texto | Critério da etapa |
| count | inteiro | Repositórios que passaram na etapa |
| discarded | inteiro | Repositórios descartados nessa etapa |
| discard_reasons | texto | Motivos e contagens (`no_actions`, `few_releases`, `few_workflow_runs`, `few_valid_workflow_runs`, `archived`, `api_error_<status>`) |

## data/raw/screening.csv: uma linha por candidato avaliado

| Coluna | Tipo | Descrição / origem |
|---|---|---|
| rank | inteiro | Ordem do candidato na busca (`/search/repositories`, estrelas desc.) |
| full_name | texto | `owner/repo` |
| stars | inteiro | `stargazers_count` |
| language | texto | `language` (linguagem principal) |
| stage | texto | Última etapa alcançada (`eligible` = entra na amostra) |
| discard_reason | texto | Motivo do descarte |
| n_workflows | inteiro | Workflows do repositório (`/actions/workflows`) |
| n_releases_window | inteiro | Releases publicadas, não pré-release, na janela |
| n_push_runs_total | inteiro | `total_count` de `/actions/runs?branch=<default>&event=push` na janela (todas as conclusões) |
| n_valid_runs | inteiro | Runs com `conclusion` ∈ {success, failure, timed_out, startup_failure} |
| n_compares | inteiro | Chamadas `compare` feitas (pares de releases) |
| n_compare_errors | inteiro | Pares com erro (404 = tag apagada/reescrita) |
| contributors | inteiro | Contribuidores (`/contributors?per_page=1&anon=true`, última página do `Link`) |
| elapsed_s | real | Segundos gastos na triagem/coleta do candidato |

## data/raw/execution_log.csv: uma linha por execução da coleta

Ver a lista de colunas em `docs/decisoes-metodologicas.md`, seção 11. Tempo total da
coleta = soma de `duration_min`; chamadas à API = soma de `api_calls`.

## data/raw/token_events.csv: eventos de tokens

| Coluna | Tipo | Descrição |
|---|---|---|
| timestamp | data/hora local | Momento do evento |
| event | texto | `switch` (troca de token), `exhausted` (cota zerada), `all_exhausted_wait` (todos sem cota, aguardando), `secondary_limit_wait` |
| resource | texto | `core`, `search` ou `graphql` |
| token | texto | Últimos 4 caracteres do token |
| previous, previous_remaining, new_remaining, reset, wait_s | variado | Detalhes do evento |

## data/raw/collect.log

Log completo da saída do terminal de todas as execuções.

## data/raw/repos/<owner>__<repo>.json

Dados brutos (enxutos) de cada repositório elegível: metadados, workflows, releases
(com corpo das release notes truncado em 2.000 caracteres), commits de cada `compare`,
workflow runs e tags. É a entrada do passo `dataset`.

## data/processed/repositories_metrics.csv: uma linha por repositório da amostra

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| repo | texto | | `full_name` |
| stars | inteiro | estrelas | `stargazers_count` |
| language | texto | | `language` |
| contributors | inteiro | pessoas | ver acima |
| created_at | data | | `created_at` do repositório |
| age_years | real | anos | (fim da janela − `created_at`) / 365,25 |
| default_branch | texto | | `default_branch` |
| n_workflows | inteiro | | workflows do repositório |
| n_releases | inteiro | releases | releases publicadas (`draft=false`, `prerelease=false`) na janela |
| n_releases_with_pre | inteiro | releases | idem, incluindo pré-releases |
| n_tags | inteiro | tags | tags cujo commit (`author.date`) está na janela |
| n_valid_runs / n_failed_runs / n_success_runs | inteiro | runs | runs de `push` no default branch, classificados pela tabela da seção 3 |
| runs_capped_days | inteiro | fatias | meses (fatias) que atingiram o teto de 1.000 runs da API; nesses meses só os 1.000 mais recentes entram |
| deployment_frequency | real | releases/semana | `n_releases / semanas da janela` (RQ 01) |
| deployment_frequency_with_pre | real | releases/semana | variante RQ 07 |
| deployment_frequency_tags | real | tags/semana | variante RQ 07 |
| lead_time_release_days | real | dias | RQ 02 (a): mediana, entre releases, de `published_at(R) − min(commit.author.date)` dos commits de `compare/{anterior}...{R}` |
| lead_time_commit_days | real | dias | RQ 02 (b): mediana de `published_at(R) − commit.author.date` de todos os commits |
| lead_time_*_with_pre | real | dias | mesmas variantes considerando a release anterior de qualquer tipo |
| n_releases_lead_time / n_commits_lead_time | inteiro | | amostras usadas no cálculo |
| n_compare_errors | inteiro | releases | releases ignoradas no lead time por erro no `compare` |
| cfr_ci | real | proporção de 0 a 1 | RQ 03 (a): falhas / (falhas + sucessos) |
| cfr_delivery | real | proporção de 0 a 1 | RQ 03 (b): releases seguidas por release corretiva em ≤ 7 dias / releases avaliadas |
| n_releases_cfr_evaluated | inteiro | | denominador do CFR (b) |
| n_releases_cfr_censored | inteiro | | releases nos últimos 7 dias da janela (censuradas) |
| rework_rate | real | proporção de 0 a 1 | RQ 08: releases corretivas (heurística v6) / releases na janela |
| recovery_hours | real | horas | RQ 04: mediana dos episódios (`updated_at` do sucesso − `run_started_at` da 1ª falha), por workflow |
| n_recovery_episodes | inteiro | | episódios encerrados |
| n_recovery_censored | inteiro | | episódios sem recuperação até o fim da janela |
| recovery_censored_ratio | real | proporção de 0 a 1 | censurados / (encerrados + censurados) |
| class_c1_* | texto | Elite/High/Medium/Low | C1 (referência): release, lead time (a), CFR (a), recuperação |
| class_c2_* | texto | Elite/High/Medium/Low | C2: release + pré-release, lead time (b), CFR (b), recuperação |

**Heurística de release corretiva (v6, adotada após a validação):** a versão é um patch da
própria linha MAJOR.MINOR (PATCH > 0, por exemplo 2.3.1 ou 8.4.15) **e** as release notes
têm pelo menos tantos termos de correção (`fix`, `bug`, `hotfix`, `regression`, `crash`,
`patch`, `revert`, `security`, `cve`...) quanto de funcionalidade (`feature`, `new`, `added`,
`support`, `enhancement`, `improvement`...). Tags fora do SemVer: mais termos de correção
que de funcionalidade. F1 = 0,781 contra o consenso da amostra-ouro (v1: 0,602). Todas as
versões testadas estão em `reports/resultados/validacao/heuristica.md`.

**CFR (b):** a release R falha se a **próxima release estável da mesma linha MAJOR.MINOR**
sair em até 7 dias e for corretiva. Em repositórios que mantêm várias linhas, a próxima
release por data pode ser um backport de outra linha e não corrige R.

## data/processed/releases.csv: uma linha por release na janela

`repo`, `tag_name`, `published_at`, `prerelease`, `html_url`, `previous_tag` (release estável anterior),
`compare_status` (`ok`, `truncated` = release com mais de 2.000 commits, só os 2.000 mais antigos foram baixados, `first_release`, `error_<status>`), `total_commits_api` (`total_commits` do compare), `n_commits`, `oldest_commit_date`,
`lead_time_release_days` (dias), `patch_bump` (bool: só o PATCH mudou em relação à release estável anterior por data),
`has_fix_commit` (bool), `line_patch` (bool: PATCH > 0, patch da própria linha), `notes_fix_terms` e
`notes_feature_terms` (inteiros: termos de correção e de funcionalidade nas release notes),
`is_corrective_v1` (bool: heurística v1, mantida para comparação), `is_corrective` (bool: heurística
v6, usada no CFR b e no rework rate), `cfr_b_status` (`failed`, `ok`, `censored`).

## data/processed/release_commits.csv.gz: commits incluídos em cada release

Não versionado (~190 MB compactado). Gerado localmente por `python -m pipeline --config config.toml --step dataset`.

`repo`, `release_tag`, `release_published_at`, `sha`, `author_date` (`commit.author.date`),
`lead_time_days` (dias), `message` (primeira linha, até 300 caracteres).

## data/processed/workflow_runs.csv.gz

`repo`, `run_id`, `workflow_id`, `workflow_name`, `conclusion`, `classification`
(`success`, `failure`, `ignored`), `created_at`, `run_started_at`, `updated_at`, `head_sha`.

## data/processed/recovery_episodes.csv

`repo`, `workflow_id`, `recovery_hours` (horas; vazio se censurado), `censored` (bool).

## data/processed/tags.csv

`repo`, `tag`, `sha`, `commit_author_date` (data do commit apontado pela tag).

## data/processed/gold_sample_template.csv

Sorteio reproduzível (semente `seed` do config, padrão 42) de 60 repositórios e 5 releases
estáveis de cada, com links diretos para a release e para o `compare`. Colunas em branco
para rotular: `tipo_projeto`, `entrega_real`, `release_corretiva`. Cada integrante copia
o arquivo e rotula de forma independente.

## data/processed/summary.csv

Mediana, Q1, Q3 e IQR de cada métrica na amostra.
