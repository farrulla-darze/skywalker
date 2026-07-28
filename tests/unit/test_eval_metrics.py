"""Unit tests: deterministic retrieval metrics."""

from app.modules.evaluation.metrics import (
    aggregate,
    hit_at_k,
    mrr,
    normalize_url,
    recall_at_k,
)


def test_normalize_url_ignores_scheme_www_and_trailing_slash():
    assert normalize_url("https://www.infinitepay.io/maquininha/") == "infinitepay.io/maquininha"
    assert normalize_url("http://infinitepay.io/maquininha") == "infinitepay.io/maquininha"


def test_recall_at_k():
    gold = ["https://a.io/1", "https://a.io/2"]
    retrieved = ["https://www.a.io/1", "https://b.io/x", "https://a.io/2"]
    assert recall_at_k(gold, retrieved, k=3) == 1.0
    assert recall_at_k(gold, retrieved, k=1) == 0.5
    assert recall_at_k([], retrieved, k=3) == 0.0


def test_hit_at_k():
    gold = ["https://a.io/1"]
    assert hit_at_k(gold, ["https://b.io", "https://a.io/1"], k=2) == 1.0
    assert hit_at_k(gold, ["https://b.io", "https://a.io/1"], k=1) == 0.0


def test_mrr_uses_first_gold_rank():
    gold = ["https://a.io/1"]
    assert mrr(gold, ["https://b.io", "https://a.io/1"]) == 0.5
    assert mrr(gold, ["https://a.io/1"]) == 1.0
    assert mrr(gold, ["https://b.io"]) == 0.0


def test_aggregate_means():
    result = aggregate([{"m": 1.0}, {"m": 0.0}])
    assert result == {"m": 0.5}
    assert aggregate([]) == {}
