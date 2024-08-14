from typing import List


def break_paragraphs(text: str) -> List[str]:
    """Breaks the given text into paragraphs, removing empty lines and leading/trailing whitespace"""
    result = [p.strip() for p in text.split("\n")]
    return [p for p in result if p]


def merge_paragraphs_to_canonical_text(paragraphs: List[str]) -> str:
    """Converts the given list of paragraphs into a canonical text representation"""
    return "\n\n".join(paragraphs)
