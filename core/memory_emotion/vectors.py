"""core/memory_emotion/vectors.py — semantic memory, v1 parity
(2026-07-12). Ports the concept pair shared_embedder + vector store
from the predecessor engine: SentenceTransformer all-MiniLM-L6-v2,
CPU-forced (Blackwell/sm_120 CUDA quirk, documented in the v1 bone),
lazy singleton, graceful None when unavailable.

v2 differences, deliberate: embeddings are DERIVED data — a
regenerable sidecar (vectors.npy float32 N x 384, row-aligned with
vectors_ids.json), never a second source of truth; memories.json
remains the single store. No ChromaDB: the corpus is small enough
that a normalized matrix dot IS the index. Vectors are L2-normalized
at embed time so dot product = cosine."""
import json
import os

_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def get_embedder():
    """Lazy CPU singleton (v1 idiom verbatim). None if unavailable —
    recall degrades to keyword overlap, receipted, never crashes."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(_MODEL_NAME, device="cpu")
        except Exception as e:
            print(f"[vectors] embedder unavailable ({e}) — "
                  f"keyword fallback stays in effect")
            _model = False
    return _model or None


def embed_texts(texts: list):
    """Apply one shared embedding policy to every derived sidecar.

    Documents and memories keep separate canonical stores, but they share the
    model, normalization, and batching rule used for semantic navigation.
    """
    model = get_embedder()
    if model is None:
        return None
    import numpy as np
    vectors = model.encode(
        list(texts), convert_to_numpy=True, normalize_embeddings=True,
        batch_size=64, show_progress_bar=False)
    return np.asarray(vectors, dtype="float32")


class VectorStore:
    """The sidecar. Load is cheap (npy mmap-able). The organ performs one
    explicit boot probe; direct tool/fixture stores remain lazy until asked."""

    def __init__(self, organ_dir: str):
        self.dir = organ_dir
        self.vec_path = os.path.join(organ_dir, "vectors.npy")
        self.ids_path = os.path.join(organ_dir, "vectors_ids.json")
        self.matrix = None          # numpy (N, 384) or None
        self.ids = []               # row-aligned record ids
        self.row = {}               # id -> row index
        self._pending = []          # (id, text) awaiting embed+save
        self._embedder_healthy = None
        try:
            if os.path.exists(self.vec_path) \
                    and os.path.exists(self.ids_path):
                import numpy as np
                self.matrix = np.load(self.vec_path)
                with open(self.ids_path, encoding="utf-8") as handle:
                    self.ids = json.load(handle)
                self.row = {i: r for r, i in enumerate(self.ids)}
        except Exception as e:
            print(f"[vectors] sidecar load failed ({e}) — "
                  f"starting empty; backfill regenerates")
            self.matrix, self.ids, self.row = None, [], {}

    def boot_health_check(self, memory_ids, persona="unknown") -> dict:
        """Probe once at organ construction; status reads never retry it."""
        self._embedder_healthy = get_embedder() is not None
        status = self.health_status(memory_ids)
        state = "HEALTHY" if self._embedder_healthy else "UNAVAILABLE"
        print(
            f"[JNSQ EMBEDDER HEALTH] {persona} {state} "
            f"model={_MODEL_NAME} sidecar="
            f"{status['covered']}/{status['records']}",
            flush=True)
        return status

    def health_status(self, memory_ids) -> dict:
        """Read-only projection of the boot result and current sidecar coverage."""
        ids = list(memory_ids)
        covered = sum(1 for mem_id in ids if mem_id in self.row)
        state = ("healthy" if self._embedder_healthy is True else
                 "unavailable" if self._embedder_healthy is False else
                 "unchecked")
        return {
            "status": state,
            "healthy": self._embedder_healthy,
            "model": _MODEL_NAME,
            "covered": covered,
            "records": len(ids),
            "sidecar_rows": len(self.ids),
            "coverage": covered / len(ids) if ids else None,
        }

    def coverage(self, ids) -> float:
        ids = list(ids)
        if not ids:
            return 0.0
        return sum(1 for i in ids if i in self.row) / len(ids)

    def _embed(self, texts: list):
        return embed_texts(texts)

    def add(self, mem_id: str, text: str):
        """Best-effort, batched via save(): encode-time never blocks
        on the model; the pending list flushes when the organ saves."""
        if mem_id and text:
            self._pending.append((mem_id, (text or "")[:600]))

    def checkpoint(self) -> int:
        """Mark the reversible pending tail before a canonical transaction."""
        return len(self._pending)

    def rollback_pending(self, checkpoint: int) -> None:
        """Forget only embeds queued after a failed canonical transaction."""
        checkpoint = int(checkpoint)
        if checkpoint < 0 or checkpoint > len(self._pending):
            raise ValueError("invalid vector pending checkpoint")
        del self._pending[checkpoint:]

    def save(self):
        if not self._pending:
            return 0
        pend = [(i, t) for i, t in self._pending if i not in self.row]
        self._pending = []
        if not pend:
            return 0
        vecs = self._embed([t for _i, t in pend])
        if vecs is None:
            return 0
        import numpy as np
        self.matrix = (vecs if self.matrix is None
                       else np.vstack([self.matrix, vecs]))
        for i, _t in pend:
            self.row[i] = len(self.ids)
            self.ids.append(i)
        np.save(self.vec_path + ".tmp.npy", self.matrix)
        os.replace(self.vec_path + ".tmp.npy", self.vec_path)
        with open(self.ids_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.ids, f)
        os.replace(self.ids_path + ".tmp", self.ids_path)
        return len(pend)

    def similarity(self, query: str, query_vector=None) -> dict:
        """id -> cosine in [0, 1] (negatives clamped). Empty dict when
        no data/model — callers fall back to keywords, receipted."""
        if self.matrix is None or not len(self.ids) or not query.strip():
            return {}
        if query_vector is None:
            qv = self._embed([query])
            if qv is None:
                return {}
            query_vector = qv[0]
        sims = self.matrix @ query_vector
        return {i: float(max(0.0, s)) for i, s in zip(self.ids, sims)}

    def neighbors_for_id(self, memory_id: str, eligible_ids,
                         k: int) -> tuple[list[tuple[str, float]], int]:
        """Read stored-row cosine neighbors without embedding or mutation.

        ``eligible_ids`` supplies both the admitted cohort and deterministic
        tie order.  The seed is never returned.  Coverage counts admitted
        non-seed IDs that actually have a sidecar row.
        """
        k = max(0, int(k))
        seed_row = self.row.get(str(memory_id))
        if k <= 0 or self.matrix is None or seed_row is None:
            return [], 0
        admitted = []
        for order, candidate_id in enumerate(eligible_ids):
            candidate_id = str(candidate_id)
            candidate_row = self.row.get(candidate_id)
            if candidate_id == str(memory_id) or candidate_row is None:
                continue
            admitted.append((order, candidate_id, candidate_row))
        if not admitted:
            return [], 0
        rows = [item[2] for item in admitted]
        scores = self.matrix[rows] @ self.matrix[seed_row]
        ranked = sorted(
            ((float(max(0.0, score)), order, candidate_id)
             for score, (order, candidate_id, _row) in
             zip(scores, admitted)),
            key=lambda item: (-item[0], item[1]))
        return ([(candidate_id, score)
                 for score, _order, candidate_id in ranked[:k]],
                len(admitted))
