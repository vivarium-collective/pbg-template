"""Safe edits to workspace pyproject.toml [project.dependencies]."""
from __future__ import annotations
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


def _find_deps_array_bounds(text: str) -> tuple[int, int] | None:
    """Return (body_start, body_end) of the [project.dependencies] array body.

    Handles brackets inside quoted strings (e.g. jsonschema[format-nongpl]).
    Returns the span of everything *between* 'dependencies = [' and the matching ']'.
    Returns None if the array is not found.
    """
    # Find `dependencies = [`
    head_m = re.search(r"dependencies\s*=\s*\[", text)
    if not head_m:
        return None

    # Walk forward from the '[' to find the matching ']',
    # skipping brackets that appear inside quoted strings.
    start_bracket = head_m.end() - 1  # position of '['
    pos = start_bracket + 1
    depth = 1
    in_single = False
    in_double = False
    while pos < len(text) and depth > 0:
        ch = text[pos]
        if in_double:
            if ch == '"' and text[pos - 1:pos] != '\\':
                in_double = False
        elif in_single:
            if ch == "'" and text[pos - 1:pos] != '\\':
                in_single = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
        pos += 1

    if depth != 0:
        return None  # unbalanced

    # body is between start_bracket+1 and pos-1 (the closing ']')
    return start_bracket + 1, pos - 1


def add_dependency(pyproject_path: Path, package: str, *, version_spec: str | None = None) -> bool:
    """Append `package[version_spec]` to [project.dependencies] if not already present.

    Returns True if a change was made; False if the dep was already declared.
    """
    if not pyproject_path.exists():
        raise FileNotFoundError(pyproject_path)

    text = pyproject_path.read_text()
    data = tomllib.loads(text)
    deps = data.get("project", {}).get("dependencies", []) or []

    # Match existing dep by package name (ignoring version constraint / extras).
    pkg_re = re.compile(r"^\s*" + re.escape(package) + r"(\s*[\[<>=!~]|\s*$)")
    for d in deps:
        if pkg_re.match(d):
            return False  # Already declared

    new_dep = f"{package}{version_spec}" if version_spec else package

    bounds = _find_deps_array_bounds(text)
    if bounds is None:
        # No dependencies array — add one to [project] section.
        proj_m = re.search(r"^\s*\[project\]\s*$", text, re.MULTILINE)
        if not proj_m:
            raise ValueError("pyproject.toml has no [project] section")
        insertion = f'\ndependencies = [\n    "{new_dep}",\n]\n'
        text = text[:proj_m.end()] + insertion + text[proj_m.end():]
    else:
        body_start, body_end = bounds
        body = text[body_start:body_end]
        existing = body.rstrip()
        trailing_comma = existing.endswith(",")
        if not existing.strip():
            new_body = f'\n    "{new_dep}",\n'
        elif trailing_comma:
            new_body = body.rstrip() + f'\n    "{new_dep}",\n'
        else:
            new_body = body.rstrip() + f',\n    "{new_dep}",\n'
        text = text[:body_start] + new_body + text[body_end:]

    pyproject_path.write_text(text)
    return True
