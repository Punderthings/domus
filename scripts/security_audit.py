"""Check every locked dependency for known vulnerabilities and write a Markdown report.

Maintainers run this by hand from time to time; it is not part of CI. It
audits the exact versions pinned in ``uv.lock`` and
``src/frontend/package-lock.json``, including dev and build tools:

- Python: ``pip-audit`` (run through ``uvx``, so it is never added to the
  project) against the PyPI vulnerability feed (PyPA advisory database).
- npm: ``npm audit`` against the GitHub Advisory Database. It reads only the
  lockfile, so ``node_modules`` need not exist.

Usage, from the repository root (needs uv, npm, and network access)::

    uv run python scripts/security_audit.py --output security-audit.md

Exit status: 0 when no advisories are found, 1 when any are found, 2 when a
tool could not run. The report is written in every case, so a failed tool is
recorded in it.
"""

import argparse
import datetime
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Pinned so a report says exactly which tool produced it. Apache-2.0.
PIP_AUDIT = "pip-audit==2.10.1"
FRONTEND_DIR = Path("src") / "frontend"

UV_EXPORT = ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--all-extras"]


@dataclass
class Result:
    """What a command printed and how it exited."""

    returncode: int
    stdout: str
    stderr: str = ""


Runner = Callable[[Sequence[str], Path], Result]


def run(cmd: Sequence[str], cwd: Path) -> Result:
    """Run ``cmd`` in ``cwd`` without a shell, capturing its output."""
    # The commands are fixed lists built in this file, never user input, and no shell is used.
    try:
        proc = subprocess.run(  # noqa: S603
            list(cmd), cwd=cwd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        return Result(127, "", str(exc))
    return Result(proc.returncode, proc.stdout, proc.stderr)


@dataclass
class Package:
    name: str
    version: str
    kind: str  # "runtime" or "dev"


@dataclass
class Finding:
    package: str
    version: str
    kind: str
    advisory: str
    severity: str
    fix: str
    summary: str


@dataclass
class Section:
    """The audit of one ecosystem."""

    title: str
    tool: str
    packages: list[Package] = field(default_factory=lambda: list[Package]())
    findings: list[Finding] = field(default_factory=lambda: list[Finding]())
    error: str | None = None


def parse_requirements(text: str) -> dict[str, str]:
    """Map package name to version from ``uv export`` output."""
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.strip()] = version.strip()
    return pins


def _one_line(text: str, limit: int = 120) -> str:
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _error(result: Result) -> str:
    return _one_line(result.stderr or result.stdout or f"exit status {result.returncode}", 300)


def audit_python(root: Path, runner: Runner) -> Section:
    section = Section("Python (uv.lock)", f"`{PIP_AUDIT}` via `uvx`, PyPI vulnerability feed")
    everything = runner([*UV_EXPORT, "--all-groups"], root)
    runtime = runner([*UV_EXPORT, "--no-dev"], root)
    for result in (everything, runtime):
        if result.returncode != 0:
            section.error = f"`uv export` failed: {_error(result)}"
            return section
    pins = parse_requirements(everything.stdout)
    runtime_names = {name.lower() for name in parse_requirements(runtime.stdout)}
    kinds = {name: "runtime" if name.lower() in runtime_names else "dev" for name in pins}
    section.packages = [Package(n, v, kinds[n]) for n, v in sorted(pins.items())]

    with tempfile.TemporaryDirectory() as tmp:
        reqs = Path(tmp) / "requirements.txt"
        reqs.write_text("".join(f"{n}=={v}\n" for n, v in pins.items()), encoding="utf-8")
        cmd = ["uvx", PIP_AUDIT, "-r", str(reqs), "--no-deps", "--disable-pip", "-f", "json"]
        audit = runner(cmd, root)
    # pip-audit exits 1 when it finds vulnerabilities; the JSON is still valid.
    try:
        data: dict[str, Any] = json.loads(audit.stdout)
    except json.JSONDecodeError:
        section.error = f"pip-audit failed: {_error(audit)}"
        return section
    for dep in data.get("dependencies", []):
        name = dep.get("name", "")
        kind = next((k for n, k in kinds.items() if n.lower() == name.lower()), "dev")
        for vuln in dep.get("vulns", []):
            ids = [vuln.get("id", "?"), *vuln.get("aliases", [])]
            section.findings.append(
                Finding(
                    package=name,
                    version=dep.get("version", ""),
                    kind=kind,
                    advisory=", ".join(ids),
                    severity="not reported",
                    fix=", ".join(vuln.get("fix_versions", [])) or "none yet",
                    summary=_one_line(vuln.get("description", "")),
                )
            )
    return section


def lock_packages(lock: Mapping[str, Any]) -> list[Package]:
    """List every package in an npm v2/v3 lockfile, deduplicated by name and version."""
    seen: dict[tuple[str, str], str] = {}
    for path, info in lock.get("packages", {}).items():
        if not path or "node_modules/" not in path:
            continue
        key = (path.rsplit("node_modules/", 1)[-1], info.get("version", ""))
        kind = "dev" if info.get("dev") else "runtime"
        # A version used anywhere at runtime counts as runtime.
        if seen.get(key) != "runtime":
            seen[key] = kind
    return [Package(n, v, k) for (n, v), k in sorted(seen.items())]


def _fix_text(fix: Any) -> str:
    if fix is True:
        return "yes (`npm audit fix`)"
    if isinstance(fix, dict):
        info: dict[str, Any] = fix  # pyright: ignore[reportUnknownVariableType]
        major = " (semver major)" if info.get("isSemVerMajor") else ""
        return f"{info.get('name', '?')}@{info.get('version', '?')}{major}"
    return "none yet"


def audit_npm(root: Path, runner: Runner) -> Section:
    section = Section(
        "npm (src/frontend/package-lock.json)", "`npm audit`, GitHub Advisory Database"
    )
    frontend = root / FRONTEND_DIR
    try:
        lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        section.error = f"cannot read package-lock.json: {exc}"
        return section
    section.packages = lock_packages(lock)
    kinds = {p.name: p.kind for p in section.packages if p.kind == "runtime"}

    audit = runner(["npm", "audit", "--json", "--package-lock-only"], frontend)
    # npm audit exits 1 when it finds vulnerabilities; the JSON is still valid.
    try:
        data: dict[str, Any] = json.loads(audit.stdout)
    except json.JSONDecodeError:
        section.error = f"npm audit failed: {_error(audit)}"
        return section
    if "error" in data:
        section.error = f"npm audit failed: {_one_line(json.dumps(data['error']), 300)}"
        return section
    for name, vuln in sorted(data.get("vulnerabilities", {}).items()):
        advisories: list[Any] = [v for v in vuln.get("via", []) if isinstance(v, dict)]
        versions = sorted({p.version for p in section.packages if p.name == name})
        common = {
            "package": name,
            "version": ", ".join(versions) or vuln.get("range", ""),
            "kind": kinds.get(name, "dev"),
            "fix": _fix_text(vuln.get("fixAvailable")),
        }
        if not advisories:
            # Vulnerable only through a dependency that has its own row.
            via = ", ".join(str(v) for v in vuln.get("via", []))
            section.findings.append(
                Finding(
                    advisory=f"via {via}",
                    severity=vuln.get("severity", "?"),
                    summary="",
                    **common,
                )
            )
        for adv in advisories:
            url = adv.get("url", "")
            ident = url.rsplit("/", 1)[-1] if url else str(adv.get("source", "?"))
            section.findings.append(
                Finding(
                    advisory=f"[{ident}]({url})" if url else ident,
                    severity=adv.get("severity", vuln.get("severity", "?")),
                    summary=_one_line(adv.get("title", "")),
                    **common,
                )
            )
    return section


def render(sections: Sequence[Section], commit: str, today: datetime.date) -> str:
    total = sum(len(s.findings) for s in sections)
    errors = [s for s in sections if s.error]
    if errors:
        verdict = "**Incomplete:** at least one check could not run (see below)."
    elif total:
        verdict = f"**{total} advisory finding(s).**"
    else:
        verdict = "**No known vulnerabilities found.**"
    out = [
        "# Domus dependency security audit",
        "",
        f"Date: {today.isoformat()}. Commit: `{commit}`. Generated by `scripts/security_audit.py`.",
        "",
        verdict,
        "",
        "| Ecosystem | Tool | Packages | Findings |",
        "| :-- | :-- | --: | --: |",
    ]
    for s in sections:
        count = "error" if s.error else str(len(s.findings))
        out.append(f"| {s.title} | {s.tool} | {len(s.packages)} | {count} |")
    out += [
        "",
        "Runtime means installed with the app (Python core install, or npm packages not "
        "marked `dev`); everything else is dev or build tooling. Not covered: uv itself and "
        "the `uv_build` backend, which are not in the lockfile.",
    ]
    for s in sections:
        out += ["", f"## {s.title}", ""]
        if s.error:
            out += [f"**Error:** {s.error}", ""]
        if s.findings:
            out += [
                "| Package | Version | Runtime / dev | Advisory | Severity | Fix | Summary |",
                "| :-- | :-- | :-- | :-- | :-- | :-- | :-- |",
            ]
            out += [
                f"| {f.package} | {f.version} | {f.kind} | {f.advisory} | {f.severity} "
                f"| {f.fix} | {f.summary} |"
                for f in s.findings
            ]
            out.append("")
        elif not s.error:
            out += ["No advisories.", ""]
        flagged = {f.package.lower() for f in s.findings}
        out += [
            "<details><summary>All packages</summary>",
            "",
            "| Package | Version | Runtime / dev | Status |",
            "| :-- | :-- | :-- | :-- |",
        ]
        for p in sorted(s.packages, key=lambda p: (p.kind != "runtime", p.name.lower())):
            status = "advisory" if p.name.lower() in flagged else "unknown" if s.error else "clean"
            out.append(f"| {p.name} | {p.version} | {p.kind} | {status} |")
        out += ["", "</details>"]
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None, runner: Runner = run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", "-o", type=Path, default=Path("security-audit.md"))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()

    sections = [audit_python(root, runner), audit_npm(root, runner)]
    head = runner(["git", "rev-parse", "--short", "HEAD"], root)
    commit = head.stdout.strip() if head.returncode == 0 else "unknown"
    report = render(sections, commit, datetime.date.today())
    args.output.write_text(report, encoding="utf-8")

    findings = sum(len(s.findings) for s in sections)
    print(f"Wrote {args.output}: {findings} finding(s).")
    if any(s.error for s in sections):
        for s in sections:
            if s.error:
                print(f"{s.title}: {s.error}", file=sys.stderr)
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
