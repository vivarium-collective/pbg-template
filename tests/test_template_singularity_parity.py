"""Smoke test: Dockerfile and Singularity.def.j2 must stay in lockstep.

Both files describe the same runtime environment — Docker for local/CI
builds, and Singularity for HPC deployment.  Any change to one must be
reflected in the other so that a workspace behaves identically regardless
of which container runtime is used.

This test checks the source templates themselves. Scaffolding carries
both files through automatically: ``template-init.sh`` renders every
``.j2`` under ``template/`` with no per-file allowlist, and the dashboard
consumes the rendered workspace at runtime without rebuilding or
inspecting these container definitions.

Conventions tested here:
  - Base image family matches exactly.
  - System package lists are compatible (Dockerfile's set ⊆ Singularity's).
  - ``uv sync`` command is byte-for-byte identical.
  - Environment variables are identical.
  - The container entrypoint / runscript is functionally equivalent.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"

DOCKERFILE = TEMPLATE / "Dockerfile"
SINGULARITY_DEF = TEMPLATE / "Singularity.def.j2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join_continuations(text: str) -> str:
    """Join lines ended with trailing backslash (Dockerfile continuation)."""
    return re.sub(r"\\\n\s*", " ", text)


def _apt_packages(text: str) -> set[str]:
    """Extract the set of Debian packages listed in an ``apt-get install``
    invocation (continuation lines joined first)."""
    joined = _join_continuations(text)
    m = re.search(
        r"apt-get install -y --no-install-recommends\s+(.+?)(?:&&|\\n|$)",
        joined, re.DOTALL,
    )
    if not m:
        return set()
    raw = m.group(1)
    pkgs: set[str] = set()
    for tok in re.split(r"\s+", raw.strip()):
        tok = tok.strip().rstrip(",")
        if tok and not tok.startswith("&&"):
            pkgs.add(tok)
    return pkgs


def _uv_sync_cmd(text: str) -> str | None:
    """Return the ``uv sync`` invocation line, or None if missing.

    Handles both bare ``uv sync ...`` (Singularity) and
    ``RUN uv sync ...`` (Dockerfile) forms.
    """
    for line in text.splitlines():
        stripped = line.strip()
        # Strip RUN prefix from Dockerfile RUN lines.
        if stripped.startswith("RUN "):
            stripped = stripped[4:].strip()
        if stripped.startswith("uv sync"):
            return stripped
    return None


def _env_vars(text: str) -> set[str]:
    """Extract KEY=value environment declarations.

    Matches both Dockerfile ENV lines (with backslash continuation)
    and Singularity export KEY=value lines.
    """
    joined = _join_continuations(text)
    vars_: set[str] = set()

    # Dockerfile style: ENV KEY=val OTHER=val (continuations already joined)
    for m in re.finditer(r"ENV\s+(.+)", joined):
        chunk = m.group(1)
        for pair in chunk.split():
            pair = pair.strip().rstrip("\\")
            if pair and "=" in pair:
                vars_.add(pair)

    # Singularity style: export KEY=val
    for m in re.finditer(r"export\s+(\S+=\S+)", text):
        vars_.add(m.group(1))

    return vars_


def _run_command(text: str) -> str | None:
    """Extract the container entrypoint / runscript command.

    Dockerfile:  CMD ["executable", "arg1", ...] → normalised shell form
    Singularity: everything under ``%runscript``
    """
    # Dockerfile CMD as JSON array.
    m = re.search(r'CMD\s+\[(.+?)\]', text, re.DOTALL)
    if m:
        parts = re.findall(r'"([^"]*)"', m.group(1))
        if parts:
            return " ".join(parts)
    # Singularity %runscript block.
    m = re.search(r'%runscript\s*\n(.+?)(?:\n%\w|\Z)', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_both_files_exist():
    """Both files must be present (basic sanity before the diff tests)."""
    assert DOCKERFILE.is_file(), f"{DOCKERFILE} not found"
    assert SINGULARITY_DEF.is_file(), f"{SINGULARITY_DEF} not found"


def test_base_image_matches():
    """The FROM / Bootstrap+From image family must be identical."""
    docker = DOCKERFILE.read_text()
    sing = SINGULARITY_DEF.read_text()

    m_docker = re.search(r"FROM\s+(\S+)", docker)
    m_sing = re.search(r"^From:\s*(\S+)", sing, re.MULTILINE)

    assert m_docker, "Dockerfile missing FROM"
    assert m_sing, "Singularity.def.j2 missing From:"
    assert m_docker.group(1) == m_sing.group(1), (
        f"Base image mismatch: Dockerfile uses '{m_docker.group(1)}' "
        f"but Singularity uses '{m_sing.group(1)}'"
    )


def test_dockerfile_apt_packages_are_subset_of_singularity():
    """Dockerfile's apt package list must be a subset of Singularity's.

    Singularity may add extra packages (e.g. ``curl``, ``ca-certificates``)
    when the Dockerfile uses a multi-stage COPY for a tool — that's
    expected and documented in comments.  What must NOT happen is a
    package in Dockerfile that is absent from Singularity (the HPC
    runtime would be missing a dependency).
    """
    docker = DOCKERFILE.read_text()
    sing = SINGULARITY_DEF.read_text()

    docker_pkgs = _apt_packages(docker)
    sing_pkgs = _apt_packages(sing)

    assert docker_pkgs, "Could not parse apt packages from Dockerfile"
    assert sing_pkgs, "Could not parse apt packages from Singularity.def.j2"

    missing = docker_pkgs - sing_pkgs
    assert not missing, (
        f"Packages present in Dockerfile but missing from Singularity: "
        f"{sorted(missing)}"
    )


def test_uv_sync_command_identical():
    """The ``uv sync`` fallback chain must be byte-for-byte identical."""
    docker = DOCKERFILE.read_text()
    sing = SINGULARITY_DEF.read_text()

    docker_cmd = _uv_sync_cmd(docker)
    sing_cmd = _uv_sync_cmd(sing)

    assert docker_cmd, "Could not extract uv sync command from Dockerfile"
    assert sing_cmd, "Could not extract uv sync command from Singularity.def.j2"
    assert docker_cmd == sing_cmd, (
        f"uv sync command differs:\n"
        f"  Dockerfile:     {docker_cmd}\n"
        f"  Singularity:    {sing_cmd}"
    )


def test_environment_variables_match():
    """All exported environment variables must match."""
    docker = DOCKERFILE.read_text()
    sing = SINGULARITY_DEF.read_text()

    docker_vars = _env_vars(docker)
    sing_vars = _env_vars(sing)

    assert docker_vars, "Could not parse env vars from Dockerfile"
    assert sing_vars, "Could not parse env vars from Singularity.def.j2"

    # Environment must be identical in both.
    assert docker_vars == sing_vars, (
        f"Environment mismatch:\n"
        f"  Dockerfile only:          {sorted(docker_vars - sing_vars)}\n"
        f"  Singularity only:         {sorted(sing_vars - docker_vars)}"
    )


def test_entrypoint_functionally_equivalent():
    """The container entrypoint / runscript must run the same command.

    Dockerfile uses CMD with a JSON array; Singularity uses
    ``%runscript`` with a shell string.  We normalise both to a shell
    command string for comparison.
    """
    docker = DOCKERFILE.read_text()
    sing = SINGULARITY_DEF.read_text()

    docker_cmd = _run_command(docker)
    sing_cmd = _run_command(sing)

    assert docker_cmd, "Could not extract CMD from Dockerfile"
    assert sing_cmd, "Could not extract %runscript from Singularity.def.j2"

    # The Singularity runscript may start with "cd /app" and/or "exec"
    # (structural requirements of the %runscript section); strip those
    # to compare the underlying application command.
    sing_app = sing_cmd
    sing_app = re.sub(r"^cd\s+\S+\s*\n?", "", sing_app)
    sing_app = re.sub(r"^exec\s+", "", sing_app)
    sing_app = sing_app.strip()

    # The Dockerfile CMD is already the bare application command string.
    assert sing_app == docker_cmd, (
        f"Entrypoint command differs:\n"
        f"  Dockerfile CMD:       {docker_cmd}\n"
        f"  Singularity %runscript (app part): {sing_app}"
    )
