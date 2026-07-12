from collections.abc import Sequence

from fastembed import TextEmbedding

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class LocalEmbedder:
    """ONNX embeddings via fastembed: CPU-only, fully local, no API key.

    The model is downloaded once on first use and cached; embedding itself
    never touches the network.
    """

    def __init__(self) -> None:
        self._model = TextEmbedding(DEFAULT_MODEL)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(list(texts))]
