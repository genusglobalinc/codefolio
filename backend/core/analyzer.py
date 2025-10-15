"""
analyzer.py - Analyze repos for LOC, imports, languages, TODOs
"""

from collections import Counter
import re
from pathlib import Path

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w\.\-]+)", re.MULTILINE)


def analyze_repo(repo, files=None, sample_limit=8, progress_cb=None):
    meta = {
        "name": repo.name,
        "full_name": repo.full_name,
        "private": repo.private,
        "description": repo.description or "",
        "language": repo.language,
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "size_kb": repo.size,
        "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
        "topics": [],
    }

    try:
        meta["topics"] = repo.get_topics()
    except Exception:
        meta["topics"] = []

    file_count = 0
    loc = 0
    languages = Counter()
    imports = Counter()
    todo_count = 0
    samples = []

    for f in files or []:
        file_count += 1
        try:
            lines = f["content"].splitlines()
            loc += len(lines)
            if len(samples) < sample_limit:
                samples.append({"path": f["path"], "snippet": "\n".join(lines[:40])})
            ext = Path(f["path"]).suffix.lower()
            if ext:
                languages[ext] += 1
            for m in IMPORT_RE.findall(f["content"][:3000]):
                imports[m.split(".")[0]] += 1
            if re.search(r"\b(TODO|FIXME|WIP|UNFINISHED)\b", f["content"], re.IGNORECASE):
                todo_count += 1
        except Exception:
            continue

    meta.update({
        "file_count": file_count,
        "loc": loc,
        "languages_count": dict(languages.most_common(8)),
        "imports": dict(imports.most_common(12)),
        "todo_count": todo_count,
        "sample_files": samples,
    })

    # classification heuristics
    status = "Archive"
    if (file_count >= 3 and loc >= 200) or meta["stars"] > 3:
        status = "Portfolio-Ready"
    if todo_count > 0 or loc < 200:
        status = "Prototype"
    meta["status"] = status

    return meta
