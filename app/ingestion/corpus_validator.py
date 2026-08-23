"""Validador del corpus -- RFC-0002 3."""


class CorpusValidationError(ValueError):
    """El corpus incumple una regla obligatoria -- RFC-0002 3."""


def validate_corpus(text: str) -> None:
    raise NotImplementedError
