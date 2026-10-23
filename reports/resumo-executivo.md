# Mineração de métricas DORA: resumo executivo

**Lab03** · Felipe Vieira e Yan Araujo Resende · janela de 02/10/2025 a 01/10/2026 · [repositório](https://github.com/FelipeVieir4/lab03-medicao-experimentacao-software-)

Medimos as métricas DORA em **383 repositórios** populares que usam GitHub Actions: 27.571 releases, 1,2 milhão de workflow runs e cerca de 90 mil chamadas à API. A release publicada faz o papel de deploy. Para falha, usamos dois proxies: a falha de CI e a release seguida de uma correção. **Conclusão central: a velocidade se mede de forma robusta; a estabilidade depende do proxy escolhido.**

## 1. Decisões

| Decisão | Motivo | Efeito |
|---|---|---|
| Triagem da etapa mais barata para a mais cara (Actions → 5 releases → 50 runs), parando só com o lote de 100 completo | Economizar cota; o paralelismo não altera a amostra | 900 candidatos → 817 → 441 → **383** |
| Limites da API viraram cortes explícitos e registrados | Um repositório muito ativo custaria mais de mil chamadas só de runs | Meses com mais de 1.000 runs ficam com os 1.000 mais recentes (96 repositórios). O compare vai até 2.000 commits (2,6% das releases, só afeta o lead time b) |
| Casos sem desfecho dentro da janela são censurados, não descartados | Descartá-los faria os repositórios parecerem melhores | 1,0% dos episódios de falha e 4,7% das releases do CFR (b) |
| Release corretiva = patch da própria linha (PATCH > 0) **e** release notes com pelo menos tantos termos de correção quanto de funcionalidade (v6) | Escolhida entre 7 versões testadas contra o consenso humano | F1 = 0,78 (meta: 0,70); a versão inicial tinha 0,60 |
| Nenhum repositório excluído depois de ver os dados | Evitar regras ad hoc | O `expo/expo` (267 releases em 3 dias, uma por pacote) fica como exemplo de que release ≠ deploy |
| Testes não paramétricos, implementados com a biblioteca padrão e conferidos com scipy, statsmodels e scikit-learn | O scipy é bloqueado numa das máquinas | O kappa ponderado usa a ordem Low < Medium < High < Elite explícita; o scikit-learn ordena alfabeticamente e erra |
| Desempate da amostra-ouro: rótulo de um avaliador nas 86 divergências | Grupo com dois avaliadores; um aplicou o critério de forma mais consistente | Em 26% das releases, o consenso é o julgamento de uma só pessoa |

## 2. Desafios

- **Cota da API.** Foram cerca de 90 mil chamadas. O rodízio de até 5 tokens multiplicou por 2,4 as chamadas por hora (pico de 42 mil). O cache SQLite, gravado a cada resposta, fez a coleta sobreviver a cotas esgotadas e a um reinício do computador sem repetir chamadas.
- **Teto de 1.000 resultados** na busca e nos runs: a busca foi fatiada por faixas de estrelas, e os runs foram coletados mês a mês.
- **O proxy de falha de entrega.** Nem os avaliadores concordam bem sobre o que é uma release corretiva (κ = 0,48), e as quatro primeiras versões da heurística ficaram abaixo de F1 0,70 (a melhor teve 0,65). O erro estava nas releases de manutenção de linhas antigas (ex.: `php-8.4.15` depois da 8.5), comparadas com a release anterior por data. Olhando a própria linha e as release notes, a v6 chega a 0,78.
- **Dois avaliadores em vez de três:** não há maioria, e o kappa fica menos estável.

## 3. Resultados

| RQ | Resposta | Números-chave |
|---|---|---|
| 01 Frequência | Uma release a cada duas semanas, com cauda longa | 0,50 por semana (IQR 0,23–1,18); os 10% mais ativos têm 57% das releases |
| 02 Lead time | Medianas parecidas; as variantes divergem caso a caso | (a) por release 10,7 dias · (b) por commit 11,7 dias; (a) > (b) em 61% dos repositórios |
| 03 Taxa de falha | Os dois proxies medem coisas diferentes | (a) CI 4,9% · (b) entrega 20,0% · ρ = 0,15 entre elas |
| 04 Recuperação | O pipeline volta no mesmo dia | Mediana de 2,6 h; 90% em menos de 1 dia; 1% dos episódios censurados |
| 05 Velocidade × estabilidade | Relação positiva, com força que depende do proxy | ρ = 0,16 com o CFR (a) · ρ = 0,61 com o CFR (b) |
| 06 Fatores | A idade importa; a popularidade, não | Lead time de 2,9 dias (novos) contra 42,3 (antigos), ε² = 0,32. Estrelas e tipo do projeto: sem efeito |
| 07 Sensibilidade | De 1/5 a quase 1/3 muda de categoria geral; o CFR é o mais frágil | Geral: 21% a 30% mudam (κ de 0,52 a 0,70). Por métrica: frequência 12% a 26%, lead time 11% a 44%, CFR 60% (κ = 0,03) |
| 08 Rework rate | Metade das releases é corretiva | 50% das releases, 2,5 vezes o CFR (b) |
| Classificação C1 | Concentrada em High e Medium | 6,6% Elite · 42,6% High · 46,2% Medium · 4,7% Low |
| Amostra-ouro | Concordância entre os avaliadores (κ de Fleiss) | Tipo do projeto 0,88 · entrega real −0,03 (95% de acordo; paradoxo do kappa) · corretiva 0,48 |

<img class="fig" src="resultados/rq01_04/distribuicoes.png" alt="Distribuição das métricas das RQs 01 a 04" width="92%">

*Figura 1. RQs 01 a 04. Cada ponto é um repositório; as linhas tracejadas são os cortes Elite, High, Medium e Low. O CFR (a) se concentra na faixa Elite, enquanto o CFR (b) se espalha por todas as faixas.*

<img class="fig" src="resultados/rq05/dispersao.png" alt="Dispersão entre deployment frequency e CFR" width="92%">

*Figura 2. RQ 05. Com o CFR (a), a nuvem é quase plana; com o CFR (b), ela sobe. Parte da subida é artefato da janela de 7 dias, que favorece quem publica muito.*

<div class="lateral">
<img src="resultados/rq06/efeitos.png" alt="Tamanho de efeito por fator e métrica" width="100%">
<p><em>Figura 3. RQ 06. Tamanho de efeito ε² por fator e métrica (* = significativo após Holm). A idade domina o lead time; as estrelas e o tipo do projeto não importam.</em></p>
</div>

## 4. Conclusões

1. **O repositório típico é High ou Medium.** As métricas medidas no CI (CFR a e recuperação) puxam a classificação para cima. As medidas em releases (frequência e lead time) puxam para baixo.
2. **A velocidade é robusta; a estabilidade, não.** Quando a definição muda, a frequência e o lead time quase sempre mudam só para a faixa vizinha. Já trocar o proxy de falha muda a categoria de 60% dos repositórios, com concordância próxima do acaso (κ = 0,03), e muda a resposta da RQ 05.
3. **A tese do DORA de que velocidade e estabilidade não competem não se confirma** com estes proxies. Ressalvas: o CFR (b) favorece, por construção, quem publica muito, e correlação não é causalidade.
4. **O que explica o desempenho é a idade, não a popularidade.** Projetos novos entregam mais e mais rápido. Idade e número de contribuidores andam juntos (ρ = 0,56), então não dá para separar os dois efeitos.
5. **Toda afirmação sobre estabilidade em open source precisa dizer qual proxy de falha usou.** O CFR de CI quase não discrimina (82% dos repositórios são Elite). O de entrega depende da noção de release corretiva, que é ambígua até para humanos.
