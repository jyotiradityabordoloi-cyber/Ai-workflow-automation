"""Text embedders for semantic memory.

Each embedder has a ``name`` that is part of the vector collection name, so vectors from two different
models are never mixed in one index (switching provider starts a fresh collection instead of returning noise).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_STOP = frozenset(
    "a an and are as at be but by can do does for from has have i if in into is it its me my no not of on or our please "
    "so that the their them there they this to was we were what when which with you your us any all just still since get got".split()
)


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1 and t not in _STOP]
    # light stemming so "charged" / "charges" / "charge" share a bucket
    return [re.sub(r"(ing|ed|es|s)$", "", t) if len(t) > 5 else t for t in toks]


class HashEmbedder:
    """Deterministic feature-hashing bag of words (unigrams + bigrams), L2-normalised.

    No model, no network: used by the tests and usable offline. It matches shared words, not meaning."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hash{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        return h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            toks = _tokens(text)
            for f in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]:
                i, sign = self._bucket(f)
                v[i] += sign
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class OnnxMiniLM:
    """all-MiniLM-L6-v2 sentence embeddings via ChromaDB's bundled ONNX runtime (CPU, local).

    The model (~80 MB) is downloaded on first use into ~/.cache/chroma and reused afterwards."""

    name = "minilm"

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._fn = DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._fn(texts)]


def build_embedder(provider: str) -> Embedder:
    if provider == "hash":
        return HashEmbedder()
    if provider == "onnx":
        return OnnxMiniLM()
    raise ValueError(f"Unknown embedding provider {provider!r} (use 'onnx' or 'hash')")
