# Decisões metodológicas e de engenharia da coleta (Sprint 02)

Registro das escolhas feitas na implementação da coleta completa, com o motivo
de cada uma e o efeito esperado nos resultados. Serve de base para as seções de
**Metodologia** e **Ameaças à validade** do artigo. Os números citados como
"ver execução" estão em `data/raw/execution_log.csv`, `data/raw/token_events.csv`,
`data/raw/funnel.csv` e `data/raw/screening.csv`.

## 1. Janela de observação

| Item | Decisão |
|---|---|
| Janela | **2025-10-02 a 2026-10-01** (12 meses fechando em 02/10/2026, abertura da Sprint 01) |
| Motivo | O enunciado diz que a janela é fixada pelo professor na abertura do Lab03S01; o grupo não localizou a data oficial e adotou os 12 meses anteriores a essa abertura |
| Fuso | Todos os limites em UTC (`T00:00:00Z` a `T23:59:59Z`) |
| Configuração | `start_date` e `end_date` em `config.toml` |

## 2. Seleção de candidatos

1. **Busca** em `GET /search/repositories` com `stars:>=1000 archived:false fork:false`, ordenada por estrelas (decrescente).
2. **Fatiamento por estrelas:** a busca devolve no máximo 1.000 resultados por consulta. Ao fim de cada fatia, a próxima consulta usa `stars:1000..<menor contagem vista>`. Duplicatas na fronteira são descartadas pelo `full_name`.
3. **Exclusão de arquivados e forks** já na consulta: repositórios arquivados não recebem mudanças e forks duplicam o histórico do original.
4. **Critério de parada:** os candidatos são processados em lotes de 100, na ordem da busca. A coleta para quando a amostra atinge **350 repositórios elegíveis** (`target_sample`), com teto de 6.000 candidatos (`max_candidates`). O guia exige no mínimo 300 após os filtros; 350 dá folga para descartes posteriores (por exemplo, repositórios sem métricas calculáveis).
5. **Viés conhecido:** a ordem por estrelas privilegia os repositórios mais populares (ameaça à validade externa).

### 2.1 Formação da fila, paralelismo e reprodutibilidade

**Como a fila é formada**

1. A busca é consumida página a página (100 repositórios por página), em ordem decrescente de estrelas, fatia por fatia (item 2 acima). Cada repositório novo recebe um número sequencial, o **rank** (`#1`, `#2`, ...), na ordem em que chega da busca. Repositórios repetidos na fronteira entre fatias são ignorados e não recebem rank.
2. Os candidatos são separados em **lotes de 100** (`batch_size`), na ordem do rank: #1 a #100, #101 a #200, e assim por diante. A busca só avança quando o lote seguinte é necessário.
3. Cada lote vira uma **fila**. Um conjunto fixo de threads (`workers`: 2 por token, no máximo 6) retira o próximo repositório da fila assim que fica livre e executa a triagem e a coleta completa dele (seção 3).
4. **Critério de parada avaliado só entre lotes:** quando todos os repositórios do lote terminam, o pipeline conta os elegíveis acumulados. Se for menor que `target_sample` (350), forma o próximo lote; caso contrário, para. Também para se a busca acabar ou se `max_candidates` (6.000) for atingido.

**Paralelismo**

- **Entre repositórios:** as threads de `workers` processam repositórios diferentes do mesmo lote ao mesmo tempo.
- **Dentro de cada repositório:** a busca dos 13 meses de workflow runs e dos pares de releases (compare) usa até `inner_workers` (4) threads, porque essas consultas são independentes entre si.
- Como cada repositório leva um tempo diferente (um descarte por `no_actions` leva menos de um segundo; um repositório incluído e muito ativo pode levar minutos), **a ordem em que os repositórios aparecem no terminal e no `collect.log` não segue o rank**. A linha de cada um é escrita quando o processamento dele termina.

**Por que a amostra é reproduzível mesmo com paralelismo**

- A composição de cada lote depende só do rank, e o rank depende só da ordem da busca.
- A decisão de parar é tomada com o lote inteiro concluído, então a velocidade de cada thread não muda quais repositórios entram. A amostra final é **todos os elegíveis dos lotes processados**, que pode passar um pouco de 350.
- `screening.csv`, `funnel.csv` e os CSVs processados são gravados em ordem de rank, não em ordem de conclusão.
- As respostas da busca também ficam no cache. Ao retomar uma coleta interrompida, a fila é remontada idêntica, mesmo que as estrelas no GitHub tenham mudado nesse meio-tempo.
- **Limite:** uma coleta nova do zero, em outra data, pode gerar uma ordem diferente, porque as estrelas e a atividade dos repositórios mudam. Para reproduzir a mesma amostra, é preciso usar o mesmo cache (`data/cache/github_cache.sqlite`) ou a lista de `screening.csv`. Isso é relevante para a replicação cruzada (seção 9 do guia).

**Efeito na validade:** a ordenação por estrelas faz a amostra ser formada pelos repositórios mais populares que atendem aos critérios, e não por uma amostra aleatória da população com ≥ 1.000 estrelas (ameaça à validade externa).

## 3. Triagem em etapas (economia de cota)

Cada candidato passa pelas etapas da mais barata para a mais cara e é descartado
na primeira em que falhar. O motivo vai para `screening.csv` e o funil para `funnel.csv`.

| Etapa | Chamadas | Critério | Motivo de descarte |
|---|---|---|---|
| 1. Workflows | 1 | `total_count > 0` em `/actions/workflows` | `no_actions` |
| 2. Releases | 1 a 30 páginas | ≥ 5 releases publicadas (`draft=false`, `prerelease=false`) com `published_at` na janela | `few_releases` |
| 3. Contagem de runs | 1 (`per_page=1`) | `total_count` ≥ 50 runs de `push` no default branch na janela | `few_workflow_runs` |
| 4. Runs completos | até 10 por mês | ≥ 50 runs com `conclusion` ∈ {success, failure, timed_out, startup_failure} | `few_valid_workflow_runs` |
| 5. Coleta completa | variável | só para elegíveis: compare, tags, contribuidores | |

A etapa 3 é um limite superior (inclui runs `cancelled`/`skipped`), por isso a
etapa 4 confirma o mínimo com runs válidos. Erros de API definitivos em um
repositório (por exemplo, HTTP 451 ou 403 de acesso) não interrompem a coleta: o
repositório é descartado com motivo `api_error_<status>`.

## 4. Releases

- **Endpoint:** `GET /repos/{owner}/{repo}/releases`, paginado pelo cabeçalho `Link`.
- **Parada da paginação:** a lista vem da mais recente para a mais antiga. A paginação para quando já foi vista uma release estável publicada **antes** do início da janela (necessária como base do `compare` da primeira release da janela) e a página já chegou a datas anteriores à janela.
- **Teto de 30 páginas** (3.000 releases) por repositório, para conter projetos com releases automáticas diárias. Se a release anterior à janela não for alcançada, `releases_cover_previous = false` no JSON bruto.
- **Ordenação:** por `published_at`, que é a data de entrega definida no guia.
- **Release notes** guardadas truncadas em 2.000 caracteres (para a rotulagem manual da amostra-ouro).

## 5. Commits entre releases (lead time)

- **Pares comparados:**
  - definição principal (C1): cada release estável da janela contra a **release estável anterior** (que pode estar fora da janela);
  - variante RQ 07 (C2, release + pré-release): cada release da janela contra a **release anterior de qualquer tipo**.
  Quando os dois pares coincidem, o cache evita chamada repetida.
- **Paginação do compare:** `per_page=100` seguindo `Link`, porque sem paginação o endpoint devolve no máximo 250 commits.
- **Teto de 20 páginas (2.000 commits) por release.** Releases acima disso ficam com `compare_status = truncated` em `releases.csv`. Motivo: projetos muito ativos (ex.: openclaw/openclaw) têm releases com milhares de commits, o que custava centenas de chamadas por repositório. Como o compare devolve os commits do mais antigo para o mais recente, o commit mais antigo (usado no lead time por release) continua correto; o lead time por commit perde os commits mais recentes dessas releases, o que tende a **superestimar** levemente a variante (b) nesses casos. O número de releases truncadas é reportado.
- **Primeira release da história:** sem release anterior, fica fora do lead time (`compare_status = first_release`), como manda o guia.
- **Erro 404/422 no compare** (tag apagada ou reescrita): a release é ignorada no lead time e contada em `n_compare_errors`.
- **Data do commit:** `commit.author.date`. Rebases e squash merges podem distorcer essa data (ameaça à validade de construto).
- **Mensagens de commit:** só a primeira linha, até 300 caracteres (suficiente para a heurística de release corretiva).

## 6. Workflow runs

- **Filtros:** `branch=<default_branch>`, `event=push`, `created=<início>..<fim>`, `exclude_pull_requests=true`.
- **Fatiamento mensal** da janela (13 fatias: o primeiro e o último mês são parciais), como pede o guia.
- **Teto de 1.000 runs por consulta:** a API devolve no máximo 1.000 resultados por consulta filtrada. **Decisão:** não subdividir os meses que passam do teto (`split_capped_runs = false`). Nesses meses entram os 1.000 runs mais recentes, e o mês é registrado em `runs_capped_days` (JSON e `repositories_metrics.csv`).
  - *Motivo:* no teste real, um único repositório muito ativo (≈ 400 runs/dia) exigiria mais de 1.000 chamadas só de runs, consumindo um quinto da cota horária de um token. Com 300+ repositórios e prazo curto, isso tornaria a coleta inviável.
  - *Efeito:* nos meses cortados, o CFR (a) e o tempo de recuperação são calculados sobre o fim do mês. É uma amostra do próprio mês, não um viés sistemático de sucesso ou falha, mas fica registrado como ameaça à validade interna. A opção `split_capped_runs = true` permite refazer a coleta completa desses meses se houver cota.
- **Classificação** pela tabela de `conclusion` da seção 3 do guia; runs `cancelled`, `skipped`, `neutral`, `action_required`, `stale` ou em andamento são guardados mas ignorados nos cálculos.
- **Reexecuções:** a API lista a última tentativa (`run_attempt`) de cada run; tentativas anteriores não entram.

## 7. Tags (variante RQ 07)

- Coletadas pela **API GraphQL** (`refs(refPrefix: "refs/tags/")`, ordenadas por data do commit), porque a REST não traz data e exigiria uma chamada extra por tag. A GraphQL tem cota própria (5.000 pontos/h), então não compete com a REST.
- Data da tag = `authoredDate` do commit apontado (tags anotadas são resolvidas até o commit), seguindo o guia ("use a data do commit apontado pela tag").
- A paginação para ao passar do início da janela.
- O lead time por tag (que exigiria um compare por par de tags) **não** é coletado; a variante de tags é usada para a frequência de deploy.

## 8. Metadados para a RQ 06

- Estrelas, linguagem principal, data de criação (idade), arquivado, fork, licença e tópicos vêm do resultado da busca (sem chamada extra).
- **Contribuidores:** `GET /contributors?per_page=1&anon=true`, lendo o número da última página no cabeçalho `Link`, como sugere o guia. Repositórios em que a API recusa a lista (histórico grande demais) ficam com valor vazio.

## 9. Métricas calculadas (`pipeline/dataset.py`)

- **RQ 01:** releases estáveis na janela ÷ semanas da janela (≈ 52,1).
- **RQ 02 (a) e (b):** conforme o guia; mediana por repositório.
- **RQ 03 (a):** falhas ÷ (falhas + sucessos), todos os workflows juntos.
- **RQ 03 (b):** release R falha se a próxima release estável sair em até 7 dias e for corretiva. Releases nos últimos 7 dias da janela ficam fora do denominador (censura, `cfr_b_status = censored`).
- **Heurística v1 de release corretiva:** só o PATCH do SemVer muda **e** há commit com `revert`, `hotfix`, `fix`, `fixes`, `fixed` ou `bugfix` entre as duas releases. Tags fora do SemVer: basta o commit. Precisa ser validada contra a amostra-ouro (F1 ≥ 0,70); cada versão testada deve ser registrada.
- **RQ 04:** runs ordenados por `run_started_at` dentro de cada workflow; o episódio começa na primeira falha e termina no próximo sucesso (`updated_at` do sucesso − `run_started_at` da primeira falha). Falhas que abrem a janela sem sucesso anterior também iniciam episódio. Episódios sem sucesso até o fim da janela são **censurados** e contados por repositório (`n_recovery_censored`, `recovery_censored_ratio`).
- **Classificação DORA:** cortes fixos do guia; combinações C1 (release, lead time a, CFR a) e C2 (release + pré-release, lead time b, CFR b) já calculadas.
- **Estatística descritiva:** mediana, Q1, Q3 e IQR em `summary.csv`.

## 10. Amostra-ouro

Sorteio reproduzível de 60 repositórios e 5 releases estáveis de cada com
`random.Random(42)` (semente em `config.toml`, campo `seed`). A planilha
`gold_sample_template.csv` já traz links para a release e para o compare.

## 11. Engenharia: cache, rate limit, tokens e paralelismo

| Item | Decisão | Motivo |
|---|---|---|
| Cache | SQLite único (`data/cache/github_cache.sqlite`), chave = URL completa (ou consulta GraphQL), gravado a cada resposta | Retomada exata após interrupção; um arquivo em vez de dezenas de milhares de JSONs |
| Modo do SQLite | `journal_mode=PERSIST` | O modo WAL falhou com "disk I/O error" em disco montado/rede no teste real |
| Respostas enxutas | Só os campos usados são gravados (ex.: o compare sem a lista de arquivos) | Reduz bastante o tamanho do cache (a lista de arquivos domina o tamanho do compare) |
| Erros definitivos | 404, 409, 410, 422 e 451 também vão para o cache | Não repetir chamadas que falharão de novo |
| Rate limit | Lê `X-RateLimit-Remaining`/`Reset`; quando todos os tokens se esgotam, espera até o primeiro reset | Requisito do guia |
| Secondary rate limit | Respeita `Retry-After` (padrão 60 s) | Evitar bloqueio por excesso de requisições simultâneas |
| Erros 5xx e de rede | Backoff exponencial 1, 2, 4, 8, 16, 32 s (6 tentativas) | Requisito do guia |
| Respostas cortadas | Respostas compactadas (`Accept-Encoding: gzip`) e nova tentativa com backoff quando a resposta chega incompleta (`IncompleteRead`) ou com JSON truncado | Na primeira execução no Windows, respostas grandes (até ~1,2 MB por página de runs) foram cortadas em ~320 KB e três repositórios (ggml-org/llama.cpp, n8n-io/n8n, vercel/next.js) foram descartados por erro em vez de avaliados. Após a correção, a coleta foi reiniciada e esses candidatos foram reprocessados (o descarte por erro não fica salvo; só as respostas válidas vão para o cache) |
| Vários tokens | `GITHUB_TOKENS=tok1,tok2,...` no `.env`. Estratégia pegajosa: usa um token até restarem 50 chamadas e então troca para o de maior cota. Se nenhum outro token tiver mais de 50, o atual é gasto até zerar, sem trocar. Quando todos zeram, as threads esperam o primeiro reset e a espera é registrada uma única vez | Multiplica a cota horária; trocas pouco frequentes deixam o log legível |
| Paralelismo entre repositórios | 2 threads por token (máx. 6) | Aproveita a cota extra dos tokens adicionais |
| Paralelismo dentro do repositório | 4 threads para os meses de runs e para os pares de releases (`inner_workers`) | No teste, um repositório pesado sozinho segurava o lote inteiro a ~1 chamada/s |
| Ajuste no log de tokens | Na primeira execução no Windows, com os dois tokens perto de zerar, as threads alternavam entre eles a cada chamada e cada thread registrava o mesmo esgotamento e a mesma espera. Isso inflou `token_switches` e `ratelimit_wait_min` nas linhas do `execution_log.csv` anteriores à correção (01:10 de 15/10/2026). A coleta em si não foi afetada | Corrigido para que as métricas de rodízio sejam confiáveis no relatório |
| Logs | Saída no terminal e em `data/raw/collect.log`; trocas de token, esgotamentos e esperas em `data/raw/token_events.csv`; uma linha por execução em `data/raw/execution_log.csv` | Medir o ganho do rodízio e do paralelismo |
| Compatibilidade | Python ≥ 3.10 (usa `tomli` no 3.10) | O ambiente de teste tinha Python 3.10 |

### Métricas de execução registradas (`execution_log.csv`)

`started_at`, `finished_at`, `status` (completed, interrupted, error), `duration_min`,
`n_tokens`, `workers`, `inner_workers`, `api_calls`, `cache_hits`, `calls_by_token`,
`token_switches`, `ratelimit_wait_min`, `secondary_wait_s`, `retries_5xx_network`,
`backoff_s`, `candidates_processed`, `eligible`, `calls_per_hour`,
`min_hours_single_token` (= chamadas ÷ 5.000, o tempo mínimo que a mesma coleta
levaria com um token só) e `speedup_vs_single_token` (= `min_hours_single_token` ÷
duração real). Em `screening.csv`, `elapsed_s` dá o tempo gasto em cada candidato.

Como a coleta pode ser interrompida e retomada, o tempo total é a soma de
`duration_min` das linhas do `execution_log.csv`, e o total de chamadas é a soma de
`api_calls` (chamadas atendidas pelo cache não consomem cota e aparecem em `cache_hits`).

## 12. Execução da coleta (15/10/2026)

Números consolidados de `data/raw/execution_log.csv` e `data/raw/collect.log`.

### Linha do tempo

| Execução (horário de Brasília) | Tokens | Duração | Chamadas à API | Elegíveis ao fim | Observação |
|---|---|---|---|---|---|
| 00:32 a 00:35 | 2 | 2,7 min | 898 | 6 | Teste inicial em outro ambiente (registrado em UTC no log, 03:32) |
| 00:56 a 01:07 | 2 | 10,8 min | 7.856 | 24 | Interrompida para aplicar a correção de respostas cortadas (gzip) |
| 01:07 a 05:35 | 2 | 268,3 min | ≥ 49.880 | 210 | **Reconstruída do log**: o PC reiniciou durante a espera pelo reset da cota e a execução não gravou sua linha. Fim = última atividade registrada; chamadas = contador da última linha de lote (05:32) |
| 07:35 a 07:52 | 2 | 17,0 min | 10.314 | 254 | Retomada após o reinício, a partir do cache |
| 08:09 a 08:17 | 2 | 8,5 min | 22 | 254 | Tokens esgotados; aguardando reset |
| 08:18 a 08:37 | 3 | 19,8 min | 6.912 | 295 | Terceiro token adicionado |
| 08:37 a 08:42 | 4 | 5,0 min | 4.785 | 295 | Quarto token |
| 08:43 a 08:44 | 3 | 1,2 min | 269 | 295 | Reinício para ajustar o `.env` |
| 08:44 a 08:57 | 5 | 12,8 min | 9.024 | **383** | Quinto token; coleta concluída (`completed`) |

### Totais

- **Tempo ativo de coleta:** ~346 min (~5h46), soma das durações.
- **Tempo de relógio:** 00:32 às 08:57 (~8h25), incluindo ~2h parado entre o reinício do PC e a retomada.
- **Chamadas à API:** ~90 mil (o cache final tem 91.596 respostas, incluindo as da busca e da GraphQL).
- **Resultado:** 900 candidatos avaliados, 383 elegíveis, 34.935 releases e 1.342.749 workflow runs.
- **Integridade do cache:** `PRAGMA quick_check` = ok após o fim da coleta.

### Efeito do rodízio de tokens

| Fase | Tokens | Tempo ativo | Chamadas | Chamadas/hora | Elegíveis/hora | Chamadas por elegível |
|---|---|---|---|---|---|---|
| 1 (00:32 a 08:17) | 2 | ~308 min | ~69 mil | ~13 mil | ~50 | ~272 |
| 2 (08:18 a 08:57) | 3 a 5 | ~39 min | ~21 mil | ~32 mil | ~200 | ~163 |

- A vazão em **chamadas por hora** subiu cerca de **2,4 vezes**, coerente com o aumento da cota (2 × 5.000 para até 5 × 5.000 chamadas/h). A última execução, só com 5 tokens, atingiu 42 mil chamadas/h sem nenhuma espera por rate limit.
- O ganho em **elegíveis por hora** (~4 vezes) é maior que o ganho real de vazão, porque os primeiros candidatos (mais populares) são mais pesados: custaram ~272 chamadas por elegível contra ~163 na fase 2. Para comparar estratégias, a métrica justa é chamadas por hora.
- Com 2 tokens, a coleta passou boa parte de cada hora parada esperando o reset da cota (as 10 mil chamadas da hora eram consumidas em ~15 minutos). Esse é o gargalo que o rodízio de tokens resolve; o paralelismo só ajuda enquanto há cota.
- A coluna `speedup_vs_single_token` do `execution_log.csv` compara cada execução com o tempo mínimo que um único token levaria (chamadas ÷ 5.000/h).

## 13. Caso expo/expo: monorepo com uma release por pacote (#23)

O `expo/expo` aparece com 267 releases estáveis entre 29/09 e 01/10/2026, todas nos
últimos 3 dias da janela. A suspeita era erro de coleta. Verificação feita direto na API
(`GET /repos/expo/expo/releases`, 8 páginas, 751 releases em 22/10/2026):

- **Não é erro de coleta.** A release mais antiga do repositório é de 29/09/2026
  (`@expo/config-types@58.0.2`). Antes disso o expo não publicava releases no GitHub, e a
  paginação parou porque a lista acabou, não por teto (`releases_cover_previous = false`).
- **O que mudou foi o processo do projeto.** O expo é um monorepo e passou a publicar uma
  release por pacote (`expo-camera@58.0.5`, `@expo/env@2.5.1`, ...). Só em 29/09 foram
  146 releases publicadas com poucos segundos de diferença.
- **Efeito nas métricas:** a deployment frequency (5,1 releases por semana) é artificial,
  porque divide releases de 3 dias por 52 semanas e conta cada pacote como um deploy. O
  compare entre releases de pacotes diferentes não tem relação com entrega (0 commits na
  maioria dos pares). Todas as releases caem nos últimos 7 dias da janela, então o CFR (b)
  fica sem valor (censura).
- **Decisão:** o repositório foi mantido na amostra, porque atende aos critérios do guia e
  removê-lo seria uma regra criada depois de ver os dados. O caso é registrado como ameaça
  à validade de construto: em monorepos que versionam por pacote, "release" não equivale
  a "deploy" do produto.

## 14. Resumo para Ameaças à validade

- **Construto:** release ≠ deploy (caso extremo: monorepos com uma release por pacote, como o expo/expo, seção 13); falha de CI ≠ falha em produção; `commit.author.date` distorcido por rebase/squash; heurística corretiva ainda não validada.
- **Interna:** meses com mais de 1.000 runs só têm os 1.000 mais recentes; releases com mais de 2.000 commits truncadas no lead time por commit; repositórios mais antigos e populares tendem a ter mais releases.
- **Externa:** amostra de repositórios open-source populares (≥ 1.000 estrelas), formada em ordem decrescente de estrelas e não por sorteio (seção 2.1); não representa projetos corporativos.
- **Conclusão:** quantidade de releases e episódios varia muito entre repositórios; medianas de poucos valores são instáveis.
