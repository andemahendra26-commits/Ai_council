"""Extracting build artifacts out of a verdict's fenced code blocks."""

from __future__ import annotations

import pytest

from council.buildzip import (
    extract_files,
    is_substantial,
    wants_build,
    _sanitize,
)


# --- filenames from the fence info string ----------------------------------

def test_filename_in_info_string():
    md = "```python app.py\nprint(1)\n```"
    assert extract_files(md) == {"app.py": "print(1)"}


def test_info_string_that_is_only_a_filename():
    md = "```main.rs\nfn main() {}\n```"
    assert extract_files(md) == {"main.rs": "fn main() {}"}


def test_language_only_info_string_falls_back_to_generic_name():
    md = "```python\nprint(1)\n```"
    assert extract_files(md) == {"file.py": "print(1)"}


# --- filenames from a hint line above the fence ----------------------------

@pytest.mark.parametrize("hint", [
    "**File:** `server.py`",
    "File: server.py",
    "`server.py`",
    "**`server.py`**",
    "### server.py",
])
def test_hint_line_above_fence(hint):
    md = f"{hint}\n```python\nx = 1\n```"
    assert extract_files(md) == {"server.py": "x = 1"}


def test_hint_is_ignored_when_it_is_not_a_filename():
    md = "Here is the answer\n```python\nx = 1\n```"
    assert extract_files(md) == {"file.py": "x = 1"}


# --- the generic-name counter (this is where the old bug lived) ------------

def test_first_generic_block_is_unnumbered_then_numbered():
    """Regression: the counter's else-branch was unreachable, so the first
    unnamed block was named `file1.py` instead of `file.py`."""
    md = "```python\naaa\n```\n\n```python\nbbb\n```\n\n```python\nccc\n```"
    assert sorted(extract_files(md)) == ["file.py", "file2.py", "file3.py"]


def test_generic_counter_is_per_extension():
    md = "```python\naaa\n```\n\n```js\nbbb\n```"
    assert sorted(extract_files(md)) == ["file.js", "file.py"]


def test_extensionless_languages_keep_their_conventional_name():
    md = "```dockerfile\nFROM python:3.12\n```"
    assert extract_files(md) == {"Dockerfile": "FROM python:3.12"}


# --- path safety ------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "etc/passwd"),
    ("/abs/path.py", "abs/path.py"),
    ("C:\\Windows\\evil.py", "Windows/evil.py"),
    ("./a/./b.py", "a/b.py"),
    ("`quoted.py`", "quoted.py"),
])
def test_sanitize_strips_traversal_and_drives(raw, expected):
    assert _sanitize(raw) == expected


def test_a_name_that_sanitizes_to_nothing_is_dropped():
    md = "```../..\nbody text here\n```"
    assert extract_files(md) == {"file.txt": "body text here"}


# --- duplicates and empties -------------------------------------------------

def test_duplicate_names_keep_the_longer_body():
    md = "```python app.py\nshort\n```\n\n```python app.py\nmuch longer body\n```"
    assert extract_files(md) == {"app.py": "much longer body"}


def test_empty_fences_are_skipped():
    assert extract_files("```python\n\n```") == {}


def test_no_fences_at_all():
    assert extract_files("just prose, no code") == {}
    assert extract_files("") == {}


# --- the two gates that decide whether a zip is offered ---------------------

@pytest.mark.parametrize("question", [
    "build me a CLI tool",
    "write a python script that renames files",
    "create a website for my band",
    "scaffold a FastAPI service",
])
def test_build_intent_is_recognised(question):
    assert wants_build(question)


@pytest.mark.parametrize("question", [
    "should we use postgres or mysql?",
    "explain how TLS works",
    "what is the best way to learn rust",
    "",
])
def test_non_build_questions_are_not_offered_a_zip(question):
    assert not wants_build(question)


def test_substantial_needs_real_content():
    assert not is_substantial({"a.sh": "ls"})
    assert is_substantial({"a.sh": "x" * 60})
    assert is_substantial({"a.py": "one\ntwo\nthree"})
    assert not is_substantial({})
