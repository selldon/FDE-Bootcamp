"""Text -> vector (IT21): fastembed `BAAI/bge-small-en-v1.5`, loaded on first use so tests and the app start without it.

`embed(texts)` returns one list of floats per text (384 numbers). `FakeEmbedder` has the same interface, is
deterministic and small: words are hashed into a few buckets, so texts that share words are close.
"""
import hashlib
import math
import re

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384

_model = None


def embed(texts):
    """One vector per text, from the real model (downloaded and loaded on the first call)."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=MODEL_NAME)
    return [[float(x) for x in vector] for vector in _model.embed(list(texts))]


class FakeEmbedder:
    DIMENSIONS = 16

    def __init__(self):
        self.calls = []
        self.fail = None

    def embed(self, texts):
        if self.fail:
            raise self.fail
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def _vector(self, text):
        vector = [0.0] * self.DIMENSIONS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vector[hashlib.sha256(word.encode()).digest()[0] % self.DIMENSIONS] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
