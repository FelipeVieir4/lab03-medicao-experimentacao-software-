from pipeline.dataset import analyse_repository, has_fix_commit, is_corrective, is_patch_bump, parse_semver


def test_semver_and_fix_heuristic():
    assert parse_semver("v2.3.1") == (2, 3, 1)
    assert parse_semver("release-1.4") == (1, 4, 0)
    assert parse_semver("nightly") is None
    assert is_patch_bump("v2.3.0", "v2.3.1") is True
    assert is_patch_bump("v2.4.0", "v2.5.0") is False
    assert is_patch_bump("nightly", "v1") is None
    assert has_fix_commit(["fix: crash ao abrir arquivo"]) and not has_fix_commit(["feat: prefix"])
    assert is_corrective("v2.3.0", "v2.3.1", ["fix: crash"]) is True
    assert is_corrective("v2.4.0", "v2.5.0", ["fix: crash"]) is False
    assert is_corrective("a", "b", ["Revert x"]) is True


def _commit(date, msg="chore"):
    return {"sha": date, "author_date": date, "message": msg}


def test_analyse_repository_guide_examples():
    rel = lambda i, tag, d, pre=False: {"id": i, "tag_name": tag, "published_at": d, "prerelease": pre, "html_url": ""}
    data = {
        "window": {"start": "2026-01-01", "end": "2026-12-31"},
        "repository": {"full_name": "o/r", "created_at": "2020-01-01T00:00:00Z"},
        "releases": [
            rel(1, "v2.2.0", "2025-12-01T00:00:00Z"),
            rel(2, "v2.3.0", "2026-03-15T00:00:00Z"),
            rel(3, "v2.3.1", "2026-03-17T00:00:00Z"),
            rel(4, "v2.4.0", "2026-06-01T00:00:00Z"),
            rel(5, "v2.5.0", "2026-06-20T00:00:00Z"),
            rel(6, "v2.6.0", "2026-12-30T00:00:00Z"),
        ],
        "compares": [
            {"base": "v2.2.0", "head": "v2.3.0", "commits": [
                _commit("2026-03-02T00:00:00Z"), _commit("2026-03-10T00:00:00Z"), _commit("2026-03-14T00:00:00Z")]},
            {"base": "v2.3.0", "head": "v2.3.1", "commits": [_commit("2026-03-16T00:00:00Z", "fix: crash ao abrir arquivo")]},
            {"base": "v2.3.1", "head": "v2.4.0", "commits": []},
            {"base": "v2.4.0", "head": "v2.5.0", "commits": [_commit("2026-06-19T00:00:00Z", "feat")]},
            {"base": "v2.5.0", "head": "v2.6.0", "error": 404, "commits": []},
        ],
        "workflow_runs": [
            {"id": 1, "workflow_id": 9, "conclusion": "success", "run_started_at": "2026-02-01T09:00:00Z", "updated_at": "2026-02-01T09:05:00Z"},
            {"id": 2, "workflow_id": 9, "conclusion": "failure", "run_started_at": "2026-02-01T10:00:00Z", "updated_at": "2026-02-01T10:05:00Z"},
            {"id": 3, "workflow_id": 9, "conclusion": "cancelled", "run_started_at": "2026-02-01T10:10:00Z", "updated_at": "2026-02-01T10:15:00Z"},
            {"id": 4, "workflow_id": 9, "conclusion": "failure", "run_started_at": "2026-02-01T10:30:00Z", "updated_at": "2026-02-01T10:35:00Z"},
            {"id": 5, "workflow_id": 9, "conclusion": "success", "run_started_at": "2026-02-01T11:15:00Z", "updated_at": "2026-02-01T11:20:00Z"},
            {"id": 6, "workflow_id": 8, "conclusion": "failure", "run_started_at": "2026-02-02T11:15:00Z", "updated_at": "2026-02-02T11:20:00Z"},
        ],
        "tags": [{"name": "v2.6.0", "author_date": "2026-12-29T00:00:00Z"}],
        "workflows": [{"id": 9}, {"id": 8}],
        "contributors": 3,
    }
    result = analyse_repository(data)
    m = result["metrics"]
    assert m["n_releases"] == 5
    # lead time (a): v2.3.0 = 13 d, v2.3.1 = 1 d, v2.5.0 = 1 d -> mediana 1; v2.4.0 sem commits é ignorada
    assert m["lead_time_release_days"] == 1
    assert m["n_compare_errors"] == 1
    # CFR (b): v2.3.0 falhou (seguida de v2.3.1 corretiva); v2.6.0 censurada (últimos 7 dias)
    statuses = {r["tag_name"]: r.get("cfr_b_status") for r in result["releases"]}
    assert statuses["v2.3.0"] == "failed" and statuses["v2.4.0"] == "ok" and statuses["v2.6.0"] == "censored"
    assert m["cfr_delivery"] == 1 / 4
    assert m["rework_rate"] == 1 / 5
    # CFR (a): 3 falhas / 5 válidos; cancelled ignorado
    assert m["cfr_ci"] == 3 / 5
    # recuperação: 10:00 -> 11:20 = 1h20; workflow 8 censurado
    assert abs(m["recovery_hours"] - 4 / 3) < 1e-9
    assert m["n_recovery_censored"] == 1 and m["recovery_censored_ratio"] == 0.5
    assert m["class_c1_overall"] in {"Elite", "High", "Medium", "Low"}


def test_single_release_repository():
    # caso de borda (seção 7): única release da história, sem release anterior nem runs
    data = {
        "window": {"start": "2026-01-01", "end": "2026-12-31"},
        "repository": {"full_name": "o/unica", "created_at": "2020-01-01T00:00:00Z"},
        "releases": [{"id": 1, "tag_name": "v1.0.0", "published_at": "2026-05-01T00:00:00Z",
                      "prerelease": False, "html_url": ""}],
        "compares": [], "workflow_runs": [], "tags": [], "workflows": [], "contributors": 1,
    }
    result = analyse_repository(data)
    m = result["metrics"]
    assert m["n_releases"] == 1
    # sem release anterior: ignorada no lead time e na heurística corretiva, sem erro de compare
    assert result["releases"][0]["compare_status"] == "first_release"
    assert m["lead_time_release_days"] is None and m["lead_time_commit_days"] is None
    assert m["n_releases_lead_time"] == 0 and m["n_compare_errors"] == 0
    assert result["releases"][0]["is_corrective_v1"] is None
    # sem release seguinte em até 7 dias: avaliada e não falhou
    assert (m["n_releases_cfr_evaluated"], m["cfr_delivery"], m["rework_rate"]) == (1, 0.0, 0.0)
    # sem runs: CFR (a) e recuperação indefinidos, logo sem classificação geral
    assert m["cfr_ci"] is None and m["recovery_hours"] is None and m["class_c1_overall"] is None


def test_heuristic_v6_and_same_line_cfr_b():
    from pipeline.dataset import is_corrective_v6, is_line_patch, notes_terms, same_line

    assert is_line_patch("v8.19.9") and not is_line_patch("v9.0.0") and is_line_patch("nightly") is None
    assert notes_terms("## Bug Fixes\n- Fixed a crash\n## Features\n- New export") == (4, 2)  # bug, fixes, fixed, crash x features, new
    assert is_corrective_v6("v2.3.1", "Fixes a regression") and not is_corrective_v6("v2.3.1", "New feature: export")
    assert not is_corrective_v6("v2.4.0", "fix fix fix")
    assert same_line("v2.3.0", "v2.3.4") and not same_line("v2.3.0", "v1.9.8") and same_line("a", "v1")

    # v9.0.0 é seguida, 2 dias depois, por um backport v8.19.9 (outra linha) e só 20 dias
    # depois pelo patch v9.0.1 da própria linha: v9.0.0 não falhou
    rel = lambda i, tag, d, body="": {"id": i, "tag_name": tag, "published_at": d, "prerelease": False,
                                      "html_url": "", "body": body}
    data = {
        "window": {"start": "2026-01-01", "end": "2026-12-31"},
        "repository": {"full_name": "o/linhas", "created_at": "2020-01-01T00:00:00Z"},
        "releases": [
            rel(1, "v8.19.8", "2026-02-01T00:00:00Z"),
            rel(2, "v9.0.0", "2026-03-01T00:00:00Z"),
            rel(3, "v8.19.9", "2026-03-03T00:00:00Z", "Bug fixes: fix crash"),
            rel(4, "v9.0.1", "2026-03-21T00:00:00Z", "Bug fixes: fix crash"),
        ],
        "compares": [], "workflow_runs": [], "tags": [], "workflows": [], "contributors": 1,
    }
    result = analyse_repository(data)
    status = {r["tag_name"]: r["cfr_b_status"] for r in result["releases"]}
    corrective = {r["tag_name"]: r.get("is_corrective") for r in result["releases"]}
    assert status["v9.0.0"] == "ok" and status["v8.19.8"] == "ok"  # v8.19.9 sai 30 dias depois da v8.19.8
    assert corrective["v8.19.9"] and corrective["v9.0.1"] and not corrective["v9.0.0"]
    assert result["metrics"]["rework_rate"] == 2 / 4
