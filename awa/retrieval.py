"""BM25 keyword retrieval in pure Python (the "R" in RAG).

Good enough for a few thousand resolved tickets and needs no embedding API.
Swap in embeddings later behind the same `search()` signature if needed.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_STOP = set("""a an and are as at be been but by can do does for from has have i if in into is it its
me my no not of on or our please so that the their them there they this to was we were what when which
with you your us any all just still since get got""".split())


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for t in toks:
        if t in _STOP or len(t) < 2:
            continue
        # light stemming so "charged"/"charge", "emails"/"email" match
        for suf in ("ing", "ed", "es", "s"):
            if len(t) > len(suf) + 3 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


class BM25:
    def __init__(self, docs: list[dict[str, Any]], fields: tuple[str, ...] = ("subject", "body"), k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(" ".join(str(d.get(f, "")) for f in fields))) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / len(self.lens) if self.lens else 0
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 3, min_score: float = 0.5) -> list[tuple[float, dict[str, Any]]]:
        q = tokenize(query)
        scored = []
        for doc, tf, ln in zip(self.docs, self.tfs, self.lens):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1)))
            if s >= min_score:
                scored.append((round(s, 2), doc))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]
