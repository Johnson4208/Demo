"""Fail a release or CI run when private runtime artifacts enter the source tree."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS = {"storage", "reports", "backups"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".zip"}


def violations():
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        parts = set(relative.parts)
        if ".git" in parts or "__pycache__" in parts:
            continue
        name = path.name.lower()
        private_environment = name == ".env" or (name.startswith(".env.") and name != ".env.example")
        private_runtime = bool(parts & FORBIDDEN_DIRS)
        private_archive = path.suffix.lower() in FORBIDDEN_SUFFIXES
        if private_environment or private_runtime or private_archive:
            found.append(relative.as_posix())
    return sorted(found)


if __name__ == "__main__":
    problems = violations()
    if problems:
        print("Private or generated artifacts must not be committed:")
        for problem in problems:
            print(f"- {problem}")
        raise SystemExit(1)
    print("Release privacy check passed.")
