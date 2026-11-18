"""Small local latent-semantic index; neither neural embeddings nor factual verification.

TF-IDF word features are compressed by TruncatedSVD to a dense LSA space.
The database remains the source of truth; this index is built on demand from
*ready* and *allowed* paper chunks and is not persisted or sent to a service.
"""

from __future__ import annotations

from typing import Sequence


def latent_candidates(conn, paper_ids: Sequence[str], query: str, *, limit=35):
    """Return (chunk_id, cosine similarity) sorted by descending LSA similarity.

    Indexing is intentionally disabled above 6500 chunks to bound CPU/RAM in a
    single-process demo. Failures here must not prevent lexical BM25 retrieval.
    """
    if not paper_ids or len(paper_ids) > 200:
        return []
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""SELECT ch.id, ch.content FROM chunks ch
            JOIN papers p ON p.id=ch.paper_id
            WHERE p.status='ready' AND ch.paper_id IN ({placeholders})
            ORDER BY ch.id LIMIT 6501""",
        tuple(paper_ids),
    ).fetchall()
    if len(rows) < 5 or len(rows) > 6500:
        return []
    texts = [row["content"][:1100] for row in rows]
    vectorizer = TfidfVectorizer(
        strip_accents="unicode", sublinear_tf=True, ngram_range=(1, 2),
        max_features=12000, min_df=1 if len(rows) < 40 else 2,
    )
    matrix = vectorizer.fit_transform(texts)
    question = vectorizer.transform([query])
    if question.nnz == 0 or min(matrix.shape) < 3:
        return []
    dims = min(48, matrix.shape[0] - 1, matrix.shape[1] - 1)
    if dims < 2:
        return []
    lsa = TruncatedSVD(n_components=dims, n_iter=3, random_state=17)
    vectors = normalize(lsa.fit_transform(matrix))
    needle = normalize(lsa.transform(question))
    if not needle.any():
        return []
    scores = vectors @ needle[0]
    chosen = sorted(range(len(rows)), key=lambda index: (-scores[index], rows[index]["id"]))
    return [
        (rows[index]["id"], round(float(scores[index]), 4))
        for index in chosen[:limit] if scores[index] >= 0.24
    ]


def reciprocal_rank_fusion(sparse_ids, dense_ids, k=40, dense_weight=0.75):
    """Merge two ranked lists by chunk ID, stable for equal scores."""
    sparse = list(dict.fromkeys(sparse_ids))
    dense = list(dict.fromkeys(dense_ids))
    scores = {}
    for rank, chunk_id in enumerate(sparse, 1):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank)
    for rank, chunk_id in enumerate(dense, 1):
        scores[chunk_id] = scores.get(chunk_id, 0) + dense_weight / (k + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
