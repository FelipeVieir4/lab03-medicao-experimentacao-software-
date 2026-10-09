# Relatório da Sprint 01

## Objetivo

Implementar a base reprodutível do pipeline de coleta das métricas DORA.

## Entregas realizadas

- Cliente REST próprio para a API do GitHub.
- Leitura do token pela variável `GITHUB_TOKEN`.
- Cache local das respostas da API para retomada da coleta.
- Paginação dos endpoints consultados.
- Retry com backoff para erros temporários.
- Tratamento básico de rate limit.
- Busca de repositórios candidatos por quantidade de estrelas.
- Coleta de workflows, releases publicadas e workflow runs de `push` no default branch.
- Filtro mínimo de 5 releases e 50 workflow runs válidos.
- Geração do funil de seleção em `data/raw/funnel.csv`.
- Funções testáveis para deployment frequency, lead time, CFR, tempo de recuperação e classificação DORA.
- Testes automatizados e workflow de CI no GitHub Actions.
- README com instruções de instalação, configuração e execução.

## Validação

- Testes executados: `6 passed`.
- Compilação dos módulos Python concluída sem erros.
- Primeira coleta executada com dois repositórios para validar o fluxo.
- Cache e dados gerados mantidos fora do controle de versão.

## Limitações atuais

- A coleta de commits entre releases ainda não está implementada.
- As métricas ainda não são consolidadas automaticamente em um dataset final.
- A busca inicial pode retornar repositórios que não atendem aos filtros mínimos; eles são registrados no funil.
- Ainda não há validação manual, análise estatística ou respostas finais para as RQs.

## Próximos passos

1. Implementar a coleta paginada de commits entre releases.
2. Consolidar os dados em CSV com dicionário de dados.
3. Completar as métricas por repositório e os casos censurados.
4. Expandir a coleta para 100 repositórios.
5. Criar as Issues e testes específicos das próximas entregas.
