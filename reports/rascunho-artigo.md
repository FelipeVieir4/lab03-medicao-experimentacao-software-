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

## 5. Resultados preliminares

Foi realizada uma execução inicial com dois candidatos para verificar o fluxo. Os dois repositórios encontrados possuíam workflows, mas não atenderam simultaneamente ao mínimo de cinco releases e cinquenta workflow runs válidos na janela configurada. Por isso, nenhum foi incluído na amostra final dessa execução piloto.

Esse resultado é apenas uma validação do pipeline, não uma conclusão sobre o desempenho DORA dos projetos.

## 6. Limitações e trabalho futuro

Ainda falta implementar a coleta de commits entre releases, a consolidação do dataset final, a validação manual, as análises estatísticas e a análise de sensibilidade. Esses itens serão realizados nas próximas Issues e sprints.

## Referências

- DORA. *DORA's software delivery metrics: the four keys*.
- Forsgren, N.; Humble, J.; Kim, G. *Accelerate: The Science of Lean Software and DevOps*.
- Wohlin, C. et al. *Experimentation in Software Engineering*.
