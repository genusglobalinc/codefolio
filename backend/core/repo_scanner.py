"""
repo_scanner.py - GitHub API interactions & file walking
"""

from github import Github
from pathlib import Path
import re

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".md",
    ".txt", ".html", ".css", ".json", ".yml", ".yaml", ".rs", ".go", ".sh"
}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w\.\-]+)", re.MULTILINE)


def connect_github(token):
    return Github(token)


def list_repos(gh, include_private=True):
    user = gh.get_user()
    repos = user.get_repos()
    result = []
    for r in repos:
        if not include_private and r.private:
            continue
        result.append(r)
    return result


def is_text_file(name):
    return any(name.lower().endswith(ext) for ext in TEXT_EXTENSIONS)


def walk_repo_files(repo, path=""):
    """
    Yield dicts for text files:
        {'path': str, 'content': str, 'sha': str}
    """
    try:
        contents = repo.get_contents(path)
    except Exception:
        return

    for item in contents:
        if item.type == "dir":
            yield from walk_repo_files(repo, item.path)
        elif item.type == "file" and is_text_file(item.name):
            try:
                raw = item.decoded_content
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    text = raw.decode("latin-1", errors="ignore")
                yield {"path": item.path, "content": text, "sha": item.sha}
            except Exception:
                continue
