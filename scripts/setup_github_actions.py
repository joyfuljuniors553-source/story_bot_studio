"""One-time setup so GitHub can run the daily videos without this PC.

Reads the private files on this machine (.env, OAuth clients, YouTube tokens),
packs them, and hands them to `gh secret set` through a pipe — the values are
never printed and never touch shell history.

    .venv\\Scripts\\python.exe scripts\\setup_github_actions.py

Re-run it whenever a token or key changes on this PC.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ci_secrets  # noqa: E402

SECRET_NAME = "BOT_SECRETS_B64"


def _gh() -> str:
    path = shutil.which("gh")
    if not path:
        raise SystemExit(
            "GitHub CLI is not installed. Get it from https://cli.github.com/ , "
            "then run:  gh auth login"
        )
    return path


def _check_auth(gh: str) -> None:
    result = subprocess.run([gh, "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("Not signed in to GitHub. Run:  gh auth login")


def _repo_env(gh: str) -> tuple[list[str], dict]:
    """`-R owner/repo` and an environment that signs in as that repo's owner.

    This PC's gh can hold several accounts, and the active one may belong to
    another bot: GitHub then answers 404 for this repository's secrets. When
    the owner of this folder's `origin` is one of the signed-in accounts, its
    token is used for this upload only; the active account is not changed.
    """
    import os
    import re

    env = dict(os.environ)
    url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        return [], env
    owner, repo = match.groups()
    if not env.get("GH_TOKEN"):
        token = subprocess.run([gh, "auth", "token", "-u", owner], capture_output=True, text=True)
        if token.returncode == 0 and token.stdout.strip():
            env["GH_TOKEN"] = token.stdout.strip()
            print(f"Using the GitHub account {owner} (owner of this repository).")
    return ["-R", f"{owner}/{repo}"], env


def main() -> None:
    gh = _gh()
    _check_auth(gh)
    repo_args, env = _repo_env(gh)

    files = [str(p.relative_to(ROOT)) for p in ci_secrets._collect()]
    if not files:
        raise SystemExit("No private files found — is this the project folder?")
    print("Packing these private files (contents are never shown):")
    for name in files:
        print(f"  - {name}")

    blob = ci_secrets.pack()
    print(f"\nUploading {len(blob) // 1024} KB to the repository secret {SECRET_NAME} ...")
    result = subprocess.run(
        [gh, "secret", "set", SECRET_NAME, *repo_args],
        input=blob, text=True, cwd=ROOT, capture_output=True, env=env,
    )
    if result.returncode != 0:
        raise SystemExit(f"gh secret set failed:\n{result.stderr.strip()}")

    print("Done.\n")
    print("GitHub can now build and upload the daily videos on its own.")
    print("Start it by hand once to check:")
    print("  gh workflow run daily-videos.yml")
    print("Then watch it:")
    print("  gh run watch")


if __name__ == "__main__":
    main()
