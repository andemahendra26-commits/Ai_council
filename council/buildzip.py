"""Turn a verdict's fenced code blocks into files, zipped for download.

When the council was asked to build something, the leader's verdict typically
contains one or more fenced code blocks. This pulls them out under whatever
filename the model gave them (a heading, a `**File:** ...` line, or a name in
the fence's info string), falling back to a generic name per language. The
browser packs the result into a zip client-side (see static/zip.js).
"""

from __future__ import annotations

import re

FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)\n?```", re.S)

# A filename token: has an extension, or a path separator, and no spaces.
FILENAME_TOKEN = re.compile(r"^[\w][\w./\\-]{0,119}\.[A-Za-z0-9]{1,10}$")

# A hint line just above a fence: **File:** `x`, File: x, **`x`**, `x`, ### x
HINT_PATTERNS = [
    re.compile(r"^\*{0,2}file\*{0,2}\s*:\s*\*{0,2}\s*`?([^`\s][^`]*?)`?\s*\*{0,2}\s*$", re.I),
    re.compile(r"^\*{0,2}`([^`\s][^`]*)`\*{0,2}\s*$"),
    re.compile(r"^#{1,6}\s+`?([^\s`][^`]*?)`?\s*$"),
]

EXT_FOR_LANG = {
    "python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts",
    "ts": "ts", "tsx": "tsx", "jsx": "jsx", "json": "json", "html": "html", "css": "css",
    "bash": "sh", "sh": "sh", "shell": "sh", "powershell": "ps1", "ps1": "ps1",
    "yaml": "yml", "yml": "yml", "toml": "toml", "sql": "sql", "java": "java",
    "go": "go", "rust": "rs", "rs": "rs", "c": "c", "cpp": "cpp", "c++": "cpp",
    "csharp": "cs", "cs": "cs", "ruby": "rb", "php": "php", "swift": "swift",
    "kotlin": "kt", "dockerfile": "Dockerfile", "text": "txt", "plaintext": "txt",
    "markdown": "md", "md": "md", "xml": "xml", "ini": "ini", "env": "env",
    "makefile": "Makefile", "make": "Makefile",
}

# Languages whose conventional filename *is* the token above, with no extension.
EXTENSIONLESS = {"Dockerfile", "Makefile"}


def _sanitize(name: str) -> str:
    """Make a model-supplied path safe to put in a zip: no escapes, no drives."""
    name = name.strip().strip("`'\"")
    name = name.replace("\\", "/")
    name = re.sub(r"^[A-Za-z]:", "", name)  # drop a Windows drive letter
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)[:200]


def _hint_before(lines: list[str], fence_start_line: int) -> str | None:
    """Look up to two non-blank lines above a fence for a filename hint."""
    seen = 0
    i = fence_start_line - 1
    while i >= 0 and seen < 2:
        text = lines[i].strip()
        if text:
            seen += 1
            for pat in HINT_PATTERNS:
                m = pat.match(text)
                if m and FILENAME_TOKEN.match(m.group(1).strip()):
                    return m.group(1).strip()
        i -= 1
    return None


def extract_files(markdown: str) -> dict[str, str]:
    """Pull named files out of a verdict's fenced code blocks."""
    if not markdown or "```" not in markdown:
        return {}

    lines = markdown.split("\n")
    line_of_offset: list[int] = []
    pos = 0
    for line in lines:
        line_of_offset.append(pos)
        pos += len(line) + 1

    files: dict[str, str] = {}
    generic_counts: dict[str, int] = {}

    for match in FENCE_RE.finditer(markdown):
        info, body = match.group(1).strip(), match.group(2)
        if not body.strip():
            continue
        start_line = next((i for i, off in enumerate(line_of_offset) if off > match.start()), len(lines)) - 1

        lang, name = "", ""
        info_parts = re.split(r"[\s:]+", info, maxsplit=1) if info else []
        if info_parts:
            lang = info_parts[0].lower()
            if len(info_parts) > 1 and FILENAME_TOKEN.match(info_parts[1].strip()):
                name = info_parts[1].strip()
        if not name and FILENAME_TOKEN.match(info):
            name = info  # the whole info string was just a filename

        if not name:
            hint = _hint_before(lines, start_line)
            if hint:
                name = hint

        if not name:
            ext = EXT_FOR_LANG.get(lang, lang if re.match(r"^[a-z0-9]{1,10}$", lang) else "txt")
            generic_counts[ext] = generic_counts.get(ext, 0) + 1
            n = generic_counts[ext]
            # Extension-only names ("Dockerfile", "Makefile") are the filename.
            if ext in EXTENSIONLESS:
                name = ext if n == 1 else f"{ext}.{n}"
            else:
                name = f"file.{ext}" if n == 1 else f"file{n}.{ext}"

        name = _sanitize(name)
        if not name:
            continue
        if name in files:  # keep the longer, presumably more complete, version
            if len(body) <= len(files[name]):
                continue
        files[name] = body

    return files


# Only offer a zip when the question itself asked for something to be built —
# a debate/analysis answer that happens to quote a one-line command shouldn't
# pop a "download build" panel. Two gates: the question reads as a build ask,
# and at least one extracted file is substantial enough to be a real artifact.
_BUILD_INTENT = re.compile(
    r"\b(build|create|generate|write|make|scaffold|implement|code|develop|produce|"
    r"design|set\s?up|put together|whip up)\b.{0,60}\b("
    r"script|scripts|app|application|apps|website|web\s?site|page|pages|program|"
    r"function|functions|class|classes|tool|tools|cli|api|bot|game|component|"
    r"components|module|modules|project|projects|library|libraries|package|"
    r"extension|plugin|website|site|server|service|microservice|snippet|utility|"
    r"utilities|automation|workflow|pipeline|dashboard|form|endpoint|schema|"
    r"file|files|repo|repository|codebase)\b",
    re.I,
)


def wants_build(question: str) -> bool:
    return bool(_BUILD_INTENT.search(question or ""))


def is_substantial(files: dict[str, str]) -> bool:
    return any(len(body) >= 60 or body.count("\n") >= 2 for body in files.values())
