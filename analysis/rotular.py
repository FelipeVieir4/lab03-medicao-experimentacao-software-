"""Ferramenta interativa para rotular a amostra-ouro (#8).

Uso: python -m analysis.rotular --avaliador <usuario-github> [--sem-navegador] [--sem-compare]

Percorre data/gold/rotulos_<avaliador>.csv e, para cada pergunta ainda sem resposta,
abre os links no navegador e lê a resposta com uma tecla. Salva a cada resposta: dá para
parar (q) e continuar depois de onde parou.

A ferramenta só lê a planilha do próprio avaliador. Ela não abre os rótulos dos colegas
nem a saída da heurística (releases.csv), como exige o protocolo (docs/protocolo-rotulagem.md).
"""
from __future__ import annotations

import argparse
import csv
import os
import webbrowser
from pathlib import Path
from typing import Callable

DEFAULT_GOLD = Path("data/gold")

# coluna -> (pergunta, {tecla: valor})
QUESTIONS = {
    "tipo_projeto": (
        "Tipo do projeto? [b] biblioteca/framework  [a] aplicação/serviço  [c] ferramenta CLI  [o] outro",
        {"b": "biblioteca", "a": "aplicacao", "c": "cli", "o": "outro"},
    ),
    "entrega_real": (
        "As releases são entregas reais ao usuário? [s] sim  [n] não  [i] incerto",
        {"s": "sim", "n": "nao", "i": "incerto"},
    ),
    "release_corretiva": (
        "Esta release é corretiva (objetivo principal: corrigir defeito recente)? [s] sim  [n] não",
        {"s": "sim", "n": "nao"},
    ),
}
REPO_COLUMNS = ("tipo_projeto", "entrega_real")
HELP = "Comandos: [r] reabrir links  [v] voltar à resposta anterior  [p] pular  [q] salvar e sair"


class Session:
    """Estado da rotulação: perguntas pendentes, respostas e histórico para desfazer."""

    def __init__(self, path: Path):
        self.path = path
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            self.fields = list(reader.fieldnames or [])
            self.rows = list(reader)
        self.history: list[tuple[str, str, str]] = []  # (coluna, repo, tag) respondidas nesta sessão
        self.skipped: set[tuple[str, str, str]] = set()

    def _repo_rows(self, repo: str) -> list[dict]:
        return [r for r in self.rows if r["repo"] == repo]

    def value(self, column: str, repo: str, tag: str) -> str:
        if column in REPO_COLUMNS:
            return next((r[column].strip() for r in self._repo_rows(repo) if r[column].strip()), "")
        return next(r[column].strip() for r in self.rows if r["repo"] == repo and r["tag_name"] == tag)

    def questions(self) -> list[tuple[str, str, str]]:
        """Todas as perguntas na ordem da planilha (dimensões de repositório na 1ª linha dele)."""
        result, seen = [], set()
        for row in self.rows:
            repo = row["repo"]
            if repo not in seen:
                seen.add(repo)
                result += [(c, repo, "") for c in REPO_COLUMNS]
            result.append(("release_corretiva", repo, row["tag_name"]))
        return result

    def pending(self) -> list[tuple[str, str, str]]:
        return [q for q in self.questions() if not self.value(*q) and q not in self.skipped]

    def progress(self) -> tuple[int, int]:
        all_q = self.questions()
        return sum(bool(self.value(*q)) for q in all_q), len(all_q)

    def set(self, column: str, repo: str, tag: str, value: str) -> None:
        targets = self._repo_rows(repo) if column in REPO_COLUMNS else [
            r for r in self.rows if r["repo"] == repo and r["tag_name"] == tag]
        for r in targets:
            r[column] = value
        if value:
            self.history.append((column, repo, tag))

    def undo(self) -> tuple[str, str, str] | None:
        if not self.history:
            return None
        question = self.history.pop()
        self.set(*question, "")
        self.skipped.discard(question)
        return question

    def save(self) -> None:
        """Grava de forma atômica, mantendo colunas, ordem e quebras de linha do arquivo."""
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(self.rows)
        os.replace(tmp, self.path)


def _links(session: Session, column: str, repo: str, tag: str) -> list[str]:
    if column in REPO_COLUMNS:
        row = session._repo_rows(repo)[0]
        return [row.get("repo_url") or f"https://github.com/{repo}"]
    row = next(r for r in session.rows if r["repo"] == repo and r["tag_name"] == tag)
    return [row.get("release_url", ""), row.get("compare_url", "")]


def label(
    session: Session,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    open_url: Callable[[str], object] | None = webbrowser.open,
    with_compare: bool = True,
) -> str:
    """Laço principal. Retorna 'concluido' ou 'interrompido'."""
    say(HELP)
    shown: set[tuple[str, str, str]] = set()  # perguntas cujo cabeçalho já foi exibido
    opened: set[str] = set()  # links já abertos (cada um abre uma vez, salvo com [r])
    while True:
        pending = session.pending()
        if not pending:
            done, total = session.progress()
            say(f"\nFim: {done}/{total} respostas preenchidas em {session.path}.")
            if session.skipped:
                say(f"{len(session.skipped)} pergunta(s) puladas: rode de novo para respondê-las.")
            return "concluido"
        question = pending[0]
        column, repo, tag = question
        done, total = session.progress()
        title, keys = QUESTIONS[column]
        links = [u for u in _links(session, column, repo, tag) if u]
        if column == "release_corretiva" and not with_compare:
            links = links[:1]
        if question not in shown:
            shown.add(question)
            say(f"\n[{done + 1}/{total}] {repo}" + (f"  release {tag}" if tag else ""))
            for url in links:
                say(f"  {url}")
                if open_url and url not in opened:
                    opened.add(url)
                    open_url(url)
        answer = ask(f"{title}\n> ").strip().lower()
        if answer in keys:
            session.set(column, repo, tag, keys[answer])
            session.save()
        elif answer == "v":
            undone = session.undo()
            if undone:
                session.save()
                shown.discard(undone)
                say(f"Desfeito: {undone[0]} de {undone[1]} {undone[2]}".rstrip())
            else:
                say("Nada para desfazer nesta sessão.")
        elif answer == "p":
            session.skipped.add(question)
        elif answer == "r":
            shown.discard(question)
            opened.difference_update(links)
        elif answer == "q":
            session.save()
            say(f"Salvo em {session.path} ({done}/{total}). Rode o mesmo comando para continuar.")
            return "interrompido"
        else:
            say(f"Resposta inválida. Use {', '.join(keys)}. {HELP}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Rotulação interativa da amostra-ouro")
    parser.add_argument("--avaliador", required=True, help="usuário do GitHub (arquivo rotulos_<avaliador>.csv)")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--sem-navegador", action="store_true", help="só mostra os links, sem abrir o navegador")
    parser.add_argument("--sem-compare", action="store_true", help="abre só a página da release, sem o compare")
    args = parser.parse_args(argv)
    path = args.gold / f"rotulos_{args.avaliador}.csv"
    if not path.exists():
        raise SystemExit(f"{path} não existe")
    try:
        label(Session(path), open_url=None if args.sem_navegador else webbrowser.open,
              with_compare=not args.sem_compare)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrompido. As respostas já dadas estão salvas.")


if __name__ == "__main__":
    main()
