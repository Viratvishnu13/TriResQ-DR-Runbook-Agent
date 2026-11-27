"""Build the upload zip from an allowlist and refuse if anything looks like a real secret.

    python scripts/package.py     # writes dist/Team31_UseCase22_Final.zip [extra files...]
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["README.md", "main.py", "requirements.txt", "azure.yaml", ".env.example", ".gitignore"]
FOLDERS = ["drill", "web", "knowledge", "scenarios", "tests", "evals", "scripts", "docs"]
SECRET = re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def env_values():
    """Secret values from .env, used only to make sure none of them appears in a packaged file."""
    path = ROOT / ".env"
    if not path.is_file():
        return []
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        if re.search(r"(?i)key|secret|token|endpoint", name) and len(value.strip().strip("\"'")) >= 8:
            values.append(value.strip().strip("\"'").encode())
    return values


def main():
    paths = [ROOT / f for f in FILES]
    for folder in FOLDERS:
        paths += [p for p in sorted((ROOT / folder).rglob("*"))
                  if p.is_file() and "__pycache__" not in p.parts]
    private = env_values()
    problems = [str(p.relative_to(ROOT)) for p in paths
                if SECRET.search(p.read_bytes()) or any(v in p.read_bytes() for v in private)]
    if problems:
        print("NOT PACKAGED - possible secret in:", ", ".join(problems))
        return 1
    out = ROOT / "dist" / "Team31_UseCase22_Final.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in paths:
            archive.write(p, p.relative_to(ROOT).as_posix())
        for extra in map(Path, sys.argv[1:]):  # e.g. the completed template, added at the zip root
            if SECRET.search(extra.read_bytes()):
                raise SystemExit(f"Possible secret in {extra.name}")
            archive.write(extra, extra.name)
    print(f"{out}  ({len(paths)} files, {out.stat().st_size // 1024} KB)")
    print("Secret scan passed. Excluded by design: .env, data/ (signing key and drill database), .venv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
