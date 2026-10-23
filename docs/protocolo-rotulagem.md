# Protocolo de rotulagem e desempate da amostra-ouro

Base: seção 6 do enunciado. Issues: #7 (sorteio), #8 (rotulação), #9 (consenso e kappa)
e #10 (avaliação da heurística).

## 1. Amostra

60 repositórios e 5 releases estáveis de cada (300 linhas), sorteados com `seed = 42` por
`pipeline/dataset.py` (`gold_sample`). Cada avaliador tem a sua cópia da planilha em
`data/gold/rotulos_<usuario-github>.csv`, com as mesmas linhas e na mesma ordem.

## 2. Rotulação independente (#8)

- Cada avaliador rotula **sozinho**: não consulta os colegas, não abre os arquivos dos
  outros e **não olha a saída da heurística** (`is_corrective_v1` em `releases.csv`).
- Só se preenchem as três colunas finais. As demais (repo, tag e links) não são alteradas.
- O arquivo é commitado na issue #8 depois de rotulado por inteiro.

### Ferramenta de rotulação (opcional)

```bash
python -m analysis.rotular --avaliador <usuario-github>
```

A ferramenta percorre a planilha do avaliador, abre no navegador o repositório, a release
e o compare, e lê cada resposta com uma tecla: `b`/`a`/`c`/`o` para o tipo, `s`/`n`/`i`
para entrega real e `s`/`n` para corretiva. Os outros comandos são `v` (voltar), `p`
(pular), `r` (reabrir os links) e `q` (salvar e sair). Ela salva a cada resposta e retoma
de onde parou. Só lê a planilha do próprio avaliador, sem os rótulos dos colegas e sem a
saída da heurística. Opções: `--sem-compare` abre só a release; `--sem-navegador` apenas
mostra os links.

| Coluna | Nível | Valores aceitos | Como decidir |
|---|---|---|---|
| `tipo_projeto` | repositório | `biblioteca`, `aplicacao`, `cli`, `outro` | Pelo README: biblioteca/framework (é importada por outro código), aplicação/serviço (é executada ou implantada pelo usuário final), ferramenta de linha de comando, ou outro (docs, listas, dados, modelos) |
| `entrega_real` | repositório | `sim`, `nao`, `incerto` | `sim` se as releases levam software utilizável ao usuário (binários, pacotes publicados, versões instaláveis); `nao` se são marcos internos, snapshots automáticos ou tags sem conteúdo; `incerto` se não dá para saber |
| `release_corretiva` | release | `sim`, `nao` | `sim` se o **objetivo principal** da release é corrigir um defeito recente, lendo as *release notes* (`release_url`) e a lista de commits (`compare_url`); `nao` se ela traz principalmente funcionalidades, melhorias ou manutenção |

As colunas de repositório podem ser preenchidas só na primeira das 5 linhas do repositório,
ou repetidas em todas. Valores diferentes no mesmo repositório são tratados como erro. O
script aceita maiúsculas, acentos e sinônimos (`não`, `Biblioteca/Framework`,
`aplicação/serviço`, `ferramenta CLI`).

## 3. Concordância (#9)

```bash
python -m analysis.concordancia
```

- **Kappa de Fleiss** em cada dimensão, calculado sobre os itens rotulados por todos os
  avaliadores. São 60 itens para tipo do projeto e entrega real, e 300 para release corretiva.
  A implementação segue Fleiss (1971), com o mesmo cálculo de `aggregate_raters` +
  `fleiss_kappa` do statsmodels. Ela foi feita com a biblioteca padrão porque o scipy, do
  qual o statsmodels depende, é bloqueado pela política de segurança de uma das máquinas
  do grupo. Os testes conferem o resultado com o exemplo do artigo original (κ = 0,210).
- **Interpretação** (Landis & Koch, 1977): < 0 pobre; até 0,20 leve; até 0,40 razoável;
  até 0,60 moderada; até 0,80 substancial; acima de 0,80 quase perfeita.

## 4. Consenso e desempate (#9)

1. **Unanimidade ou maioria simples:** o rótulo vale direto (`origem = unanime` ou `maioria`).
2. **Sem maioria** (com dois avaliadores, qualquer divergência; com três, os casos 1-1-1):
   o item vai para `data/gold/divergencias.csv`, com o rótulo de cada avaliador.
3. **Reunião de desempate:** os avaliadores discutem cada caso juntos, relendo as *release
   notes* e os commits, e registram na planilha o rótulo final (`decisao`) e o motivo
   (`justificativa`). Se ainda assim não houver acordo, prevalece o rótulo mais
   conservador: `nao` para release corretiva, `incerto` para entrega real e `outro` para
   tipo do projeto. Esse caso é anotado na justificativa.
4. Rodar `python -m analysis.concordancia` de novo. As decisões são preservadas e entram
   em `data/gold/consenso.csv` com `origem = reuniao`. Itens ainda sem decisão aparecem
   como `pendente` e ficam fora da avaliação da heurística.

O kappa é sempre calculado sobre os rótulos **independentes**, antes do consenso.

### Desempate aplicado (reunião de 23/10/2026)

Houve 86 divergências: 78 de release corretiva, 5 de tipo do projeto e 3 de entrega real.
Na reunião, os dois avaliadores concluíram que um deles (yanresende) tinha aplicado o
critério de forma mais consistente. Por isso, **o rótulo desse avaliador foi adotado em
todas as 86 divergências**, sem revisão caso a caso. Isso fica registrado na coluna
`justificativa` de `data/gold/divergencias.csv`.

Consequência para a validade: nos 78 casos divergentes de release corretiva (26% das 300
releases), o consenso coincide com um único avaliador. A avaliação da heurística (#10) é,
portanto, uma comparação com o consenso nos 222 casos unânimes e com o julgamento de um
só avaliador nos demais. Isso é registrado como ameaça à validade de construto.

## 5. Avaliação da heurística (#10)

```bash
python -m analysis.heuristica
```

- Compara cada versão da heurística de release corretiva com o consenso
  (`release_corretiva`), tendo `sim` como classe positiva. Calcula precisão, recall e F1,
  como `precision_recall_fscore_support(average='binary')`.
- Releases sem release estável anterior não têm valor da heurística e ficam de fora.
- Todas as versões testadas e o F1 de cada uma ficam registrados em
  `reports/resultados/validacao/heuristica.csv`, que vai para o artigo.
- Se nenhuma versão atingir **F1 ≥ 0,70**:
  1. analisar os erros em `heuristica_detalhe.csv`;
  2. propor uma nova versão em `analysis/heuristica.py` (`VERSIONS`) e reavaliar;
  3. levar a versão escolhida para `pipeline/dataset.py` (`is_corrective`);
  4. recalcular o dataset com `python -m pipeline --config config.toml --step dataset`;
  5. rodar as análises de novo.
