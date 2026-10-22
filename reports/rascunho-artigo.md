# Mineração de Métricas DORA em Repositórios Open Source

## Resumo

Este trabalho apresenta a construção de um pipeline reprodutível para coletar dados públicos de repositórios GitHub e inferir métricas DORA por meio de proxies. A primeira etapa implementa a coleta de repositórios candidatos, workflows, releases e execuções de CI, além de cache, paginação, tratamento de falhas e testes automatizados. Os resultados empíricos das métricas e das questões de pesquisa serão incluídos após a coleta da amostra final.

## 1. Introdução

As métricas DORA são usadas para avaliar velocidade e estabilidade na entrega de software. Entretanto, repositórios open source não registram diretamente todos os eventos necessários, como deploys em produção e falhas de produção. Portanto, este estudo utiliza releases publicadas como proxy de deploy e workflow runs do GitHub Actions como proxy de execução de CI.

O objetivo inicial é construir um pipeline reprodutível que permita coletar os dados, calcular as métricas e avaliar as limitações dessas aproximações.

## 2. Hipóteses iniciais

- **RQ 01:** repositórios populares que usam CI/CD apresentarão frequências de release diferentes entre si, com concentração em poucos projetos mais ativos.
- **RQ 02:** o lead time por commit será menor e menos sensível a commits antigos do que o lead time por release.
- **RQ 03:** a taxa de falha do proxy de CI não será equivalente à taxa de falha de entrega, pois os conceitos medidos são diferentes.
- **RQ 04:** parte dos episódios de falha permanecerá censurada ao final da janela de observação.
- **RQ 05:** espera-se uma relação fraca ou inexistente entre frequência de deploy e taxa de falha.
- **RQ 06:** popularidade, idade, número de contribuidores e linguagem poderão estar associados a diferenças nas métricas DORA.
- **RQ 07:** as classificações dos repositórios poderão mudar conforme a definição operacional utilizada.

## 3. Metodologia inicial

O pipeline utiliza a API REST do GitHub sem bibliotecas prontas de acesso à API. A coleta é configurada por uma janela de observação, uma consulta de estrelas e um limite de candidatos.

A unidade principal de deploy é uma release publicada, sem draft e sem prerelease. As execuções consideradas são workflow runs do default branch disparadas por `push`. Conclusões `success`, `failure`, `timed_out` e `startup_failure` são classificadas; execuções canceladas ou inconclusivas são ignoradas.

As respostas da API são armazenadas em cache local. O pipeline gera arquivos JSON por repositório e um CSV com o funil de seleção.

## 4. Implementação da Sprint 01

A arquitetura foi dividida em configuração, cliente GitHub, coleta, métricas e testes. O cliente implementa paginação, cache, retries e tratamento básico de rate limit. O coletor busca candidatos e coleta workflows, releases e workflow runs. O módulo de métricas é independente da API e possui testes unitários.

A suíte atual possui seis testes automatizados e é executada localmente e no GitHub Actions.

## 5. Resultados

Esta seção apresenta os resultados das RQs 01 a 05 sobre a amostra final de **383 repositórios**, na janela de 02/10/2025 a 01/10/2026. Seguindo o enunciado, cada métrica é resumida pela mediana e pelo intervalo interquartil (IQR, de Q1 a Q3), pois as distribuições são muito assimétricas. A classificação DORA usa os cortes fixos da disciplina na combinação de referência **C1**: release estável, lead time (a), CFR (a) e tempo de recuperação. Todas as tabelas e figuras são regeneradas a partir de `data/processed/repositories_metrics.csv` por `python -m analysis.descritivas` e `python -m analysis.correlacoes`.

**Tabela 1. Mediana e IQR das métricas DORA (RQs 01 a 04).**

| RQ | Métrica | Unidade | n | Mediana | Q1 | Q3 | IQR |
|---|---|---|---:|---:|---:|---:|---:|
| RQ 01 | Deployment frequency | releases/semana | 383 | 0,50 | 0,23 | 1,18 | 0,95 |
| RQ 02 | Lead time (a): por release | dias | 383 | 10,67 | 3,82 | 38,11 | 34,29 |
| RQ 02 | Lead time (b): por commit | dias | 383 | 11,72 | 3,17 | 48,93 | 45,76 |
| RQ 03 | CFR (a): falha de pipeline | proporção | 383 | 0,049 | 0,023 | 0,113 | 0,089 |
| RQ 03 | CFR (b): falha de entrega | proporção | 381 | 0,167 | 0,024 | 0,364 | 0,340 |
| RQ 04 | Tempo de recuperação | horas | 364 | 2,63 | 1,11 | 6,68 | 5,56 |

**Tabela 2. Classificação DORA na combinação C1 (% sobre os repositórios classificados).**

| Métrica | n | Elite | High | Medium | Low |
|---|---:|---:|---:|---:|---:|
| Deployment frequency | 383 | 9 (2,3%) | 98 (25,6%) | 176 (46,0%) | 100 (26,1%) |
| Lead time (a) | 383 | 50 (13,1%) | 97 (25,3%) | 122 (31,9%) | 114 (29,8%) |
| CFR (a) | 383 | 316 (82,5%) | 44 (11,5%) | 14 (3,7%) | 9 (2,3%) |
| Tempo de recuperação | 364 | 82 (22,5%) | 246 (67,6%) | 33 (9,1%) | 3 (0,8%) |
| **Geral** | 364 | 24 (6,6%) | 134 (36,8%) | 143 (39,3%) | 63 (17,3%) |

![Distribuição das métricas das RQs 01 a 04](resultados/rq01_04/distribuicoes.png)

*Figura 1. Distribuição das métricas das RQs 01 a 04. Caixas: Q1, mediana e Q3; bigodes: percentis 5 e 95; pontos: repositórios; linhas tracejadas: cortes da classificação DORA. Eixos em escala logarítmica, exceto o do CFR.*

### 5.1 RQ 01: frequência de deploy

O repositório típico publica **0,50 release estável por semana**, cerca de uma release a cada duas semanas (IQR de 0,23 a 1,18). Apenas 27,9% dos repositórios publicam ao menos uma release por semana, e só 9 (2,3%) alcançam a faixa Elite (≥ 7 por semana). A faixa mais comum é Medium (46,0%), seguida de Low (26,1%), isto é, menos de uma release por mês.

A distribuição tem cauda longa à direita (Figura 1): os 10% mais ativos (38 repositórios) concentram **57,0% de todas as releases** da amostra, e o maior valor (`ggml-org/llama.cpp`, 42,9 releases por semana) é mais de 80 vezes a mediana. Isso confirma a hipótese de que a frequência varia muito entre os projetos e se concentra em poucos repositórios.

### 5.2 RQ 02: lead time das mudanças

As duas variantes têm medianas próximas: **10,67 dias** na variante (a), por release, e **11,72 dias** na variante (b), por commit. A dispersão, porém, é diferente. A variante (b) tem IQR maior (45,76 contra 34,29 dias) e cauda superior mais pesada: o percentil 90 é de 266 dias, contra 135 dias na (a).

A comparação par a par mostra por que as variantes divergem:

- **Dentro de uma release**, a variante (a) é sempre a maior, porque usa o commit mais antigo. Um único commit "esquecido" faz o lead time daquela release explodir. Por isso, em **60,6%** dos repositórios a variante (a) supera a (b), e a mediana da razão (a)/(b) é 1,27.
- **No agregado do repositório**, a ponderação é diferente. A variante (a) dá o mesmo peso a cada release, enquanto a (b) dá peso a cada commit. Em projetos que alternam releases pequenas e frequentes com releases grandes que acumulam meses de trabalho, as releases grandes dominam a variante (b) e puxam sua mediana para cima. Esse efeito explica os 39,2% de repositórios em que (b) > (a).

A hipótese de que a variante (b) seria menor e menos sensível a commits antigos se confirma, portanto, só parcialmente. Ela vale para a maioria dos repositórios, mas a variante (b) é mais sensível ao tamanho das releases. Na classificação C1, que usa a variante (a), o lead time é a métrica mais espalhada entre as faixas: 13,1% Elite, 25,3% High, 31,9% Medium e 29,8% Low. Uma ressalva: 719 releases (2,6%) tinham mais de 2.000 commits, e só os 2.000 mais antigos foram coletados.

### 5.3 RQ 03: taxa de falha das mudanças

As duas variantes de CFR medem coisas diferentes e produzem valores bem diferentes:

- **CFR (a), falha de pipeline:** mediana de **4,9%** (IQR de 2,3% a 11,3%). Com esse valor, 82,5% dos repositórios caem na faixa Elite (≤ 15%), o que torna o CFR (a) a métrica menos discriminante de C1.
- **CFR (b), falha de entrega:** mediana de **16,7%** (IQR de 2,4% a 36,4%), mais de três vezes a do CFR (a) e com dispersão quase quatro vezes maior. Com essa variante, só 48,0% dos repositórios seriam Elite. Além disso, 87 repositórios (22,8%) não tiveram nenhuma release seguida de correção em até 7 dias (CFR (b) = 0).

A correlação de Spearman entre as variantes é fraca: ρ = 0,138 (p = 0,007, n = 381). Um repositório com pipeline instável não tende a ser o mesmo que publica releases corretivas, o que confirma a hipótese de que as variantes não são equivalentes. O CFR (a) registra qualquer falha de CI no default branch, inclusive testes instáveis (*flaky*) e falhas de lint corrigidas em minutos, que nunca chegam ao usuário. Já o CFR (b) se aproxima mais da definição DORA, mas depende da heurística de release corretiva (v1: só o PATCH muda e há commit com `fix`, `hotfix` ou `revert`), que **ainda está sendo validada** contra a amostra-ouro. Os valores do CFR (b) podem mudar após essa validação.

Por censura, **1.306 das 27.571 releases (4,74%)**, de 161 repositórios, ficaram fora do denominador do CFR (b) por terem sido publicadas nos últimos 7 dias da janela. Dois repositórios ficaram sem CFR (b) porque todas as suas releases caíram nesse período: `expo/expo`, com 267 releases entre 29/09 e 01/10/2026, e `Alishahryar1/free-claude-code`.

### 5.4 RQ 04: tempo de recuperação

A mediana do tempo de recuperação é de **2,63 horas** (IQR de 1,11 a 6,68 horas). A grande maioria dos repositórios recupera o pipeline no mesmo dia: 67,6% estão na faixa High (de 1 hora a menos de 1 dia) e 22,5% na Elite (menos de 1 hora). Apenas 36 (9,9%) levam um dia ou mais, e só 3 repositórios (0,8%) passam de uma semana.

Dos 36.785 episódios de falha, **382 (1,04%) foram censurados**, isto é, não tiveram recuperação até o fim da janela. Eles aparecem em 168 dos 367 repositórios com episódios, mas a mediana da proporção censurada por repositório é 0%. A hipótese de que haveria censura se confirma, mas em escala pequena. Dezenove repositórios ficaram sem tempo de recuperação: 16 não tiveram nenhum episódio de falha na janela e 3 tiveram apenas episódios censurados. Por isso, a classificação geral de C1 cobre 364 repositórios.

**Classificação geral (C1).** Combinando as quatro métricas, a amostra se divide em 6,6% Elite, 36,8% High, 39,3% Medium e 17,3% Low. O CFR (a) e o tempo de recuperação, ambos medidos sobre o CI, puxam a classificação para cima. A frequência de deploy e o lead time, medidos sobre releases, puxam para baixo.

### 5.5 RQ 05: velocidade × estabilidade

**Tabela 3. Correlação de Spearman entre deployment frequency e CFR.**

| Variante do CFR | n | ρ | p-valor | Interpretação (α = 0,05) |
|---|---:|---:|---:|---|
| (a) falha de pipeline | 383 | 0,161 | 0,002 | fraca positiva, significativa |
| (b) falha de entrega | 381 | 0,507 | < 0,001 | moderada positiva, significativa |

![Dispersão entre deployment frequency e CFR](resultados/rq05/dispersao.png)

*Figura 2. Dispersão entre deployment frequency (eixo x em escala logarítmica) e CFR nas variantes (a) e (b).*

Nas duas variantes, a correlação é **positiva**: repositórios que publicam mais releases também tendem a falhar mais. A intensidade, porém, depende da definição. Com o CFR (a), a relação é fraca (ρ = 0,161), o que está de acordo com a hipótese de relação fraca ou inexistente. Com o CFR (b), a relação é moderada (ρ = 0,507) e contraria a hipótese.

Parte dessa diferença pode ser um artefato da própria definição operacional. O CFR (b) só marca uma release como falha se a próxima sair em até 7 dias, e repositórios que publicam várias releases por semana têm, por construção, mais oportunidades de cumprir essa condição. Assim, o CFR (b) não é independente da frequência de deploy. Com esses proxies, os dados não sustentam a afirmação do DORA de que velocidade e estabilidade não competem entre si. Ainda assim, trata-se de correlação, e não de causalidade, e o efeito do proxy deve ser aprofundado na Discussão.

> *Resultados das RQs 06 e 07: a completar (Resultados, parte 2).*

### 5.8 RQ 08 (bônus): rework rate

O *rework rate* é a proporção de releases corretivas sobre o total de releases estáveis da janela, usando a mesma heurística de release corretiva do CFR (b) (v1). Resultados gerados por `python -m analysis.rework`.

**Tabela 4. Rework rate e CFR (b).**

| Métrica | Definição | n | Mediana | Q1 | Q3 | IQR | Repositórios com valor 0 |
|---|---|---:|---:|---:|---:|---:|---:|
| Rework rate | releases corretivas / releases | 383 | 0,444 | 0,215 | 0,725 | 0,509 | 4,4% |
| CFR (b) | releases seguidas de corretiva em ≤ 7 dias / releases avaliadas | 381 | 0,167 | 0,024 | 0,364 | 0,340 | 22,8% |

![Rework rate e CFR (b)](resultados/rq08/rework.png)

*Figura 3. À esquerda, distribuições do rework rate e do CFR (b) (caixas: Q1, mediana e Q3; bigodes: percentis 5 e 95). À direita, dispersão entre as duas métricas; a linha tracejada é y = x.*

No repositório típico, **44,4% das releases são corretivas**, quase três vezes a mediana do CFR (b) (16,7%). As duas métricas estão moderadamente correlacionadas (ρ = 0,484, p < 0,001, n = 381), mas o rework rate supera o CFR (b) em 85,8% dos repositórios e empata em 9,2%. Por isso, quase todos os pontos da Figura 3 ficam abaixo da diagonal.

A diferença vem do que cada métrica conta:

- **O que é contado:** o CFR (b) atribui a falha à release **quebrada**, aquela que foi seguida por uma correção. O rework rate conta as próprias releases **de correção**.
- **Janela de 7 dias:** o CFR (b) só considera correções publicadas em até 7 dias. O rework rate conta qualquer release corretiva, inclusive as que corrigem defeitos antigos ou que vêm depois de um intervalo maior.
- **Sequências de patches:** uma série como 2.3.1 → 2.3.2 → 2.3.3 conta três vezes no rework rate. No CFR (b), cada release só falha se a seguinte sair em até 7 dias.
- **Censura:** o rework rate não precisa observar o que vem depois da release, então não tem censura no fim da janela.

O rework rate mede, portanto, **quanto do esforço de entrega é gasto com retrabalho**, enquanto o CFR (b) mede **quantas entregas precisaram ser corrigidas logo em seguida**. O valor alto do rework rate também indica que a heurística v1 é ampla, já que quase toda release de patch tem algum commit com `fix`. Esses números dependem da validação da heurística contra a amostra-ouro e serão atualizados se ela for refinada.

## 6. Limitações e trabalho futuro

Ainda falta implementar a coleta de commits entre releases, a consolidação do dataset final, a validação manual, as análises estatísticas e a análise de sensibilidade. Esses itens serão realizados nas próximas Issues e sprints.

## Referências

- DORA. *DORA's software delivery metrics: the four keys*.
- Forsgren, N.; Humble, J.; Kim, G. *Accelerate: The Science of Lean Software and DevOps*.
- Wohlin, C. et al. *Experimentation in Software Engineering*.
