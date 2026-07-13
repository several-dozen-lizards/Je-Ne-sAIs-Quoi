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


class VectorStore:
    """The sidecar. Load is cheap (npy mmap-able); the model loads
    lazily on first embed (~2-4s once, v1-documented)."""

    def __init__(self, organ_dir: str):
        self.dir = organ_dir
        self.vec_path = os.path.join(organ_dir, "vectors.npy")
        self.ids_path = os.path.join(organ_dir, "vectors_ids.json")
        self.matrix = None          # numpy (N, 384) or None
        self.ids = []               # row-aligned record ids
        self.row = {}               # id -> row index
        self._pending = []          # (id, text) awaiting embed+save
        try:
            if os.path.exists(self.vec_path) \
                    and os.path.exists(self.ids_path):
                import numpy as np
                self.matrix = np.load(self.vec_path)
                self.ids = json.load(open(self.ids_path,
                                          encoding="utf-8"))
                self.row = {i: r for r, i in enumerate(self.ids)}
        except Exception as e:
            print(f"[vectors] sidecar load failed ({e}) — "
                  f"starting empty; backfill regenerates")
            self.matrix, self.ids, self.row = None, [], {}

    def coverage(self, ids) -> float:
        ids = list(ids)
        if not ids:
            return 0.0
        return sum(1 for i in ids if i in self.row) / len(ids)

    def _embed(self, texts: list):
        m = get_embedder()
        if m is None:
            return None
        import numpy as np
        v = m.encode(texts, convert_to_numpy=True,
                     normalize_embeddings=True, batch_size=64,
                     show_progress_bar=False)
        return np.asarray(v, dtype="float32")

    def add(self, mem_id: str, text: str):
        """Best-effort, batched via save(): encode-time never blocks
        on the model; the pending list flushes when the organ saves."""
        if mem_id and text:
            self._pending.append((mem_id, (text or "")[:600]))

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

    def similarity(self, query: str) -> dict:
        """id -> cosine in [0, 1] (negatives clamped). Empty dict when
        no data/model — callers fall back to keywords, receipted."""
        if self.matrix is None or not len(self.ids) or not query.strip():
            return {}
        qv = self._embed([query])
        if qv is None:
            return {}
        sims = self.matrix @ qv[0]
        return {i: float(max(0.0, s)) for i, s in zip(self.ids, sims)}
