from typing import List


def extract_format_parameter_field_name(fmt_path: str) -> List[str]:
    """Given a string like a[b][c], returns ['a', 'b', 'c']"""

    result: List[str] = []

    first_open = fmt_path.find("[")
    if first_open < 0:
        raise ValueError(
            f"string substitution {fmt_path} is not a dictionary path (no open)"
        )

    result.append(fmt_path[:first_open])

    open_at = first_open
    while True:
        close_at = fmt_path.find("]", open_at)
        if close_at < 0:
            raise ValueError(
                f"string substitution {fmt_path} is not a dictionary path (unmatched open)"
            )

        result.append(fmt_path[open_at + 1 : close_at])
        if close_at == len(fmt_path) - 1:
            return result

        if fmt_path[close_at + 1] != "[":
            raise ValueError(
                f"string substitution {fmt_path} is not a dictionary path (no open after close)"
            )
        open_at = close_at + 1
