"""
git_utils.py - optional commit & push
"""

from pathlib import Path
import git

def commit_and_push(output_dir, repo_name, dry_run=True):
    """
    Commit and push the output_dir to a GitHub repo.
    """
    repo_dir = Path(output_dir)
    if not repo_dir.exists():
        return

    try:
        g = git.Repo(repo_dir)
    except Exception:
        g = git.Repo.init(repo_dir)

    g.git.add(A=True)
    g.index.commit("Update Codefolio portfolio summaries")
    if dry_run:
        print("[dry run] Skipping push")
        return

    try:
        origin = g.remote(name="origin")
    except Exception:
        origin = g.create_remote("origin", f"git@github.com:{repo_name}.git")

    origin.push()
