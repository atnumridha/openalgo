from scripts.research_rank_all import rank_cells


def cell(name, base, stress, count=20, duplicate=False):
    return {
        "id": name,
        "base_mean": base,
        "stress_mean": stress,
        "base_count": count,
        "stress_count": count,
        "duplicate": duplicate,
    }


def test_stress_rank_precedes_base_and_does_not_convert_empty_to_zero():
    rows = [
        cell("pretty-base", 100, -10),
        cell("cost-resilient", 20, 5),
        cell("none", None, None, 0),
        cell("reused", 1000, 1000, duplicate=True),
    ]
    out = rank_cells(rows)
    assert [r["id"] for r in out if r["rank"] is not None] == ["cost-resilient", "pretty-base"]
    assert out[-2]["rank"] is None and out[-1]["rank"] is None


def test_ties_are_deterministic_and_input_is_not_mutated():
    rows = [cell("b", 20, 5), cell("a", 20, 5), cell("larger", 20, 5, 30)]
    assert [r["id"] for r in rank_cells(rows)] == ["larger", "a", "b"]
    assert all("rank" not in r for r in rows)
