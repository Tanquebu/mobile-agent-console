from dataclasses import dataclass


@dataclass(frozen=True)
class LineDelta:
    start: int
    delete_count: int
    lines: list[str]


def split_output(content: str) -> list[str]:
    return content.splitlines(keepends=True)


def line_delta(previous: str, current: str) -> LineDelta:
    before = split_output(previous)
    after = split_output(current)
    prefix = 0
    common = min(len(before), len(after))
    while prefix < common and before[prefix] == after[prefix]:
        prefix += 1

    suffix = 0
    remaining_before = len(before) - prefix
    remaining_after = len(after) - prefix
    while (
        suffix < remaining_before
        and suffix < remaining_after
        and before[-(suffix + 1)] == after[-(suffix + 1)]
    ):
        suffix += 1

    before_end = len(before) - suffix
    after_end = len(after) - suffix
    return LineDelta(
        start=prefix,
        delete_count=before_end - prefix,
        lines=after[prefix:after_end],
    )
