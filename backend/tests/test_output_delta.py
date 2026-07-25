from app.services.output_delta import line_delta, split_output


def apply_delta(previous: str, start: int, delete_count: int, lines: list[str]) -> str:
    current = split_output(previous)
    current[start : start + delete_count] = lines
    return "".join(current)


def test_line_delta_appends_output() -> None:
    delta = line_delta("$ prompt\n", "$ prompt\nresult\n")
    assert delta.start == 1
    assert delta.delete_count == 0
    assert delta.lines == ["result\n"]
    assert apply_delta("$ prompt\n", delta.start, delta.delete_count, delta.lines) == "$ prompt\nresult\n"


def test_line_delta_replaces_middle_and_preserves_unicode_and_ansi() -> None:
    previous = "header\n\x1b[31mattesa…\x1b[0m\nfooter"
    current = "header\n\x1b[32mcompletato ✓\x1b[0m\nfooter"
    delta = line_delta(previous, current)
    assert delta.start == 1
    assert delta.delete_count == 1
    assert delta.lines == ["\x1b[32mcompletato ✓\x1b[0m\n"]
    assert apply_delta(previous, delta.start, delta.delete_count, delta.lines) == current


def test_line_delta_handles_empty_and_missing_final_newline() -> None:
    for previous, current in [
        ("", "one"),
        ("one", ""),
        ("one\nlast", "one\nlast\n"),
        ("same", "same"),
    ]:
        delta = line_delta(previous, current)
        assert apply_delta(previous, delta.start, delta.delete_count, delta.lines) == current
