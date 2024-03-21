from typing import Optional, TypeVar, Union


DefaultT = TypeVar("DefaultT")


def extract_language_code(
    accept_language: Optional[str], default: DefaultT
) -> Union[str, DefaultT]:
    """Extracts the two-letter language code from the `Accept-Language` header, or returns
    the default if it is not present.

    Args:
        accept_language (Optional[str]): The `Accept-Language` header
        default (str): The default language code

    Returns:
        str: The language code
    """
    if accept_language is None or accept_language.strip() == "*":
        return default

    parts = accept_language.split(",")
    for part in parts:
        if ";" in part:
            lang, _ = part.split(";", 1)
        else:
            lang = part

        lang = lang.strip()
        if "-" in lang:
            lang = lang.split("-")[0]

        return lang

    return default


def extract_locale(
    accept_language: Optional[str], default: DefaultT
) -> Union[str, DefaultT]:
    """Attempts to extract the users locale from a language header, where a locale
    is of the form `en-US` rather than `en`
    """
    if accept_language is None or accept_language.strip() == "*":
        return default

    parts = accept_language.split(",")
    for part in parts:
        if ";" in part:
            lang, _ = part.split(";", 1)
        else:
            lang = part

        lang = lang.strip()
        if "-" in lang:
            return lang

    return default
