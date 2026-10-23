# Validação da heurística de release corretiva

Gerado por `python -m analysis.heuristica`. Releases avaliadas: 297 (127 corretivas no consenso). Excluídas: 0 sem consenso, 3 sem release anterior, 0 fora do dataset.

## Tabela: versões testadas (meta: F1 ≥ 0,70)

| Versão | Regra | VP | FP | FN | VN | Precisão | Recall | F1 | Meta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| v1 | só o PATCH muda E há commit fix/hotfix/revert (fora do SemVer: só o commit) | 78 | 54 | 49 | 116 | 0,591 | 0,614 | 0,602 | não atinge |
| v2 | há commit fix/hotfix/revert | 114 | 151 | 13 | 19 | 0,430 | 0,898 | 0,582 | não atinge |
| v3 | só o PATCH muda em relação à anterior por data | 89 | 58 | 38 | 112 | 0,605 | 0,701 | 0,650 | não atinge |
| v4 | só o PATCH muda OU há commit fix/hotfix/revert | 125 | 158 | 2 | 12 | 0,442 | 0,984 | 0,610 | não atinge |
| v5 | é patch da própria linha MAJOR.MINOR (PATCH > 0) | 118 | 82 | 9 | 88 | 0,590 | 0,929 | 0,722 | atinge |
| **v6** (adotada) | patch da própria linha E notas com termos de correção ≥ termos de funcionalidade | 107 | 40 | 20 | 130 | 0,728 | 0,843 | 0,781 | atinge |
| v7 | patch da própria linha E há commit fix/hotfix/revert | 107 | 68 | 20 | 102 | 0,611 | 0,843 | 0,709 | atinge |
