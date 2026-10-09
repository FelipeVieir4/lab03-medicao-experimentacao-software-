# Introdução e Hipóteses

## 1. Introdução

As métricas DORA (DevOps Research and Assessment) se estabeleceram como o padrão da indústria para quantificar e avaliar o desempenho de entrega de software de equipes de desenvolvimento. Ao medir o tempo e a estabilidade com que novas mudanças são enviadas para produção, tais métricas buscam promover um modelo iterativo de desenvolvimento que alia velocidade e qualidade. As métricas clássicas consistem em: *Deployment Frequency* (frequência de implantação), *Lead Time for Changes* (tempo de espera para mudanças), *Change Failure Rate* (taxa de falha de mudança) e *Failed Deployment Recovery Time* (tempo de recuperação).

No contexto de projetos de código aberto hospedados no GitHub, aplicar essas métricas impõe um desafio metodológico: o GitHub não registra "deploys em produção" nem o momento exato em que um usuário é afetado por uma "falha em produção". Em vez disso, o ciclo de desenvolvimento gira em torno de publicações de *releases* e execuções de fluxos de CI/CD via GitHub Actions. Dessa forma, é necessário estabelecer *proxies* (medidas indiretas) para mapear os dados da plataforma aos conceitos originais estabelecidos pelo DORA.

Este trabalho tem como objetivo minerar, calcular e analisar as métricas DORA a partir de dados públicos de repositórios *open-source* com uso ativo de CI/CD (GitHub Actions). Além da avaliação quantitativa e do enquadramento dos projetos segundo os padrões DORA (Elite, High, Medium, Low), o estudo realiza uma validação manual de uma amostra a fim de verificar a confiabilidade das heurísticas de mineração (análise de sensibilidade). O propósito final é entender até que ponto as definições operacionais escolhidas impactam na classificação das equipes, além de investigar correlações e características que se associam ao bom desempenho na entrega contínua de software.

## 2. Hipóteses para as Questões de Pesquisa (RQs)

Durante a fase de planejamento, formulou-se um conjunto de hipóteses iniciais para cada uma das questões de pesquisa (RQs) que guiam esta investigação:

*   **RQ 01. Qual a frequência de deploys dos repositórios populares que usam CI/CD?**
    *   *Hipótese:* Espera-se que a frequência mediana seja da categoria *High* ou *Medium* (entre mensal e semanal). Projetos *open-source* populares geralmente seguem calendários de *releases* bem definidos para não quebrar a estabilidade de seus ecossistemas de dependências, evitando publicações "diárias" para versões finais.
*   **RQ 02. Qual o tempo entre um commit e seu respectivo deploy?**
    *   *Hipótese:* Na variante "por release" (a), espera-se observar valores muito maiores de *Lead Time* devido a *commits* antigos de *branches* de vida longa sendo incorporados tarde. Na variante "por commit" (b), a mediana será menor, pois o volume de correções rápidas (*hotfixes*) e *commits* próximos à *release* puxarão o valor para baixo, enquadrando os projetos na faixa de dias a algumas poucas semanas.
*   **RQ 03. Qual a taxa de falha das mudanças entregues por esses repositórios?**
    *   *Hipótese:* Para o proxy de CI (a), a taxa de falha (falha de pipeline) deverá ser de nível *High* a *Medium* (~20-40%), visto que *pipelines* podem falhar por *timeouts*, testes frágeis e dependências externas indisponíveis. Para o proxy de entrega (b), a *Change Failure Rate* real (falhas que forçam *releases* corretivas) será muito menor, possivelmente classificando a maioria na faixa *Elite* ou *High* (abaixo de 15%).
*   **RQ 04. Qual o tempo de recuperação após uma execução de CI/CD com falha?**
    *   *Hipótese:* A mediana do tempo de recuperação deverá situar-se nas faixas *High* a *Medium* (entre horas e dias). Em ambientes abertos, as quebras de *pipeline* no *branch* principal são resolvidas por mantenedores centrais de forma colaborativa e ágil para destravar o andamento das contribuições da comunidade.
*   **RQ 05. Repositórios com maior frequência de deploy apresentam maior ou menor taxa de falha?**
    *   *Hipótese:* Assim como afirmam os estudos e os relatórios do *Accelerate State of DevOps*, espera-se encontrar uma correlação negativa moderada (ou ausência de correlação positiva) entre velocidade (*Deployment Frequency*) e instabilidade (*Change Failure Rate*). Projetos que liberam mais *releases* não devem exibir maiores taxas de falha.
*   **RQ 06. Quais características dos repositórios estão associadas a um melhor desempenho DORA?**
    *   *Hipótese:* Repositórios classificados como "ferramentas CLI" e com número de contribuidores no quartil superior tenderão a apresentar desempenhos DORA superiores, dado que a maturidade da comunidade força a adoção de boas práticas e automação de CI/CD desde o princípio.
*   **RQ 07. O quanto a classificação DORA de um repositório depende da definição operacional escolhida?**
    *   *Hipótese:* A classificação DORA será altamente dependente (sensível) à definição operacional de "unidade de deploy" e de "Lead Time". Ao incluir *tags* sem *releases* (proxy mais abrangente) ou mudar de métrica baseada em *release* para a baseada em *commit*, prevê-se que um percentual substancial (acima de 25%) dos projetos mudará de faixa de classificação DORA.
