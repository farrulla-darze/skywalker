"""Deterministic retrieval metrics — pure functions, no LLM required.

These run on every eval run (cheap, exact) and are the basis for
hyperparameter sweeps: recall@k, MRR and hit rate against gold source URLs.
"""

from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    """Normalize for comparison: strip scheme, 'www.', trailing slash and query."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}".lower()


def recall_at_k(gold_urls: list[str], retrieved_urls: list[str], k: int) -> float:
    """Fraction of gold URLs present in the top-k retrieved URLs."""
    if not gold_urls:
        return 0.0
    gold = {normalize_url(u) for u in gold_urls}
    retrieved = {normalize_url(u) for u in retrieved_urls[:k]}
    return len(gold & retrieved) / len(gold)


def hit_at_k(gold_urls: list[str], retrieved_urls: list[str], k: int) -> float:
    """1.0 if ANY gold URL appears in the top-k, else 0.0."""
    if not gold_urls:
        return 0.0
    gold = {normalize_url(u) for u in gold_urls}
    retrieved = {normalize_url(u) for u in retrieved_urls[:k]}
    return 1.0 if gold & retrieved else 0.0


def mrr(gold_urls: list[str], retrieved_urls: list[str]) -> float:
    """Reciprocal rank of the first gold URL in the retrieved list."""
    gold = {normalize_url(u) for u in gold_urls}
    for rank, url in enumerate(retrieved_urls, start=1):
        if normalize_url(url) in gold:
            return 1.0 / rank
    return 0.0


def aggregate(per_item: list[dict[str, float]]) -> dict[str, float]:
    """Mean of each metric across items."""
    if not per_item:
        return {}
    keys = per_item[0].keys()
    return {
        key: round(sum(item.get(key, 0.0) for item in per_item) / len(per_item), 4)
        for key in keys
    }
