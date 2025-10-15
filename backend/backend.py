"""
backend.py — Codefolio backend engine
- Each repo gets a single Markdown summary file.
- Uses OpenAI if available; otherwise falls back to a heuristic summary.
"""

import os
import re
from pathlib import Path
from collections import Counter

try:
    from github import Github
except Exception:
    raise RuntimeError("PyGithub required: pip install PyGithub")

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ---------------- utils ----------------
TEXT_EXTENSIONS = {".py",".js",".ts",".jsx",".tsx",".java",".c",".cpp",".md",".txt",".html",".css",".json",".yml",".yaml",".rs",".go",".sh"}
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w\.\-]+)", re.MULTILINE)

def is_text_file(name):
    return any(name.lower().endswith(ext) for ext in TEXT_EXTENSIONS)

def send_progress(cb, stage, pct=0, message=""):
    if cb:
        try:
            cb((stage, int(pct), message))
        except Exception:
            pass

# ---------------- walk repo ----------------
def walk_repo_files(repo, path=""):
    try:
        contents = repo.get_contents(path)
    except Exception:
        return
    for item in contents:
        if item.type == "dir":
            yield from walk_repo_files(repo, item.path)
        elif item.type == "file":
            if not is_text_file(item.name):
                continue
            try:
                raw = item.decoded_content
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    text = raw.decode("latin-1", errors="ignore")
                yield {"path": item.path, "content": text, "sha": item.sha}
            except Exception:
                continue

# ---------------- analyze ----------------
def analyze_repo(repo, sample_limit=8, progress_cb=None):
    send_progress(progress_cb, "analyze_repo.start", 0, f"Analyzing {repo.full_name}")
    meta = {
        "name": repo.name,
        "full_name": repo.full_name,
        "private": repo.private,
        "description": repo.description or "",
        "language": repo.language,
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "size_kb": repo.size,
    }

    file_count = 0
    loc = 0
    imports = Counter()
    todo_count = 0
    samples = []

    for f in walk_repo_files(repo, ""):
        file_count += 1
        try:
            lines = f["content"].splitlines()
            loc += len(lines)
            if len(samples) < sample_limit:
                samples.append({"path": f["path"], "snippet": "\n".join(lines[:40])})
            for m in IMPORT_RE.findall(f["content"][:3000]):
                imports[m.split(".")[0]] += 1
            if re.search(r"\b(TODO|FIXME|WIP|UNFINISHED)\b", f["content"], re.IGNORECASE):
                todo_count += 1
        except Exception:
            continue

    meta.update({
        "file_count": file_count,
        "loc": loc,
        "imports": dict(imports.most_common(12)),
        "todo_count": todo_count,
        "samples": samples
    })

    status = "Archive"
    if (file_count >= 3 and loc >= 200) or meta["stars"] > 3:
        status = "Portfolio-Ready"
    if todo_count > 0 or loc < 200:
        status = "Prototype"
    meta["status"] = status

    send_progress(progress_cb, "analyze_repo.done", 100, f"Analyzed {repo.full_name}")
    return meta

# ---------------- summarization ----------------
def ai_summarize(repo_meta, readme_text=None, openai_key=None):
    # OpenAI version
    if OPENAI_AVAILABLE and openai_key:
        try:
            openai.api_key = openai_key
            prompt = [
                "You are a developer writing a portfolio-quality summary for a GitHub project.",
                f"Project: {repo_meta.get('name')}",
                f"Description: {repo_meta.get('description') or 'No description'}",
                f"Primary language: {repo_meta.get('language')}",
                f"Files: {repo_meta.get('file_count')} | LOC: {repo_meta.get('loc')} | TODOs: {repo_meta.get('todo_count')}",
                "Top imports: " + ", ".join(list(repo_meta.get("imports", {}).keys())[:8]),
            ]
            if readme_text:
                prompt.append("\nREADME excerpt:\n" + readme_text[:3000])
            prompt.append("\nWrite a 3-5 sentence portfolio-style summary mentioning tech stack, GUI/API features, state, next steps.")
            full_prompt = "\n".join(prompt)
            resp = openai.Completion.create(
                engine="text-davinci-003",
                prompt=full_prompt,
                temperature=0.18,
                max_tokens=220,
                top_p=1
            )
            return resp.choices[0].text.strip()
        except Exception:
            pass

    # Fallback heuristic
    lines = [
        f"# {repo_meta.get('name')}\n",
        f"**Description:** {repo_meta.get('description') or 'No description'}",
        f"**Status:** {repo_meta.get('status')}",
        f"**Primary Language:** {repo_meta.get('language')}",
        f"**Files:** {repo_meta.get('file_count')} | LOC: {repo_meta.get('loc')} | TODOs: {repo_meta.get('todo_count')}",
        f"**Top Imports:** {', '.join(list(repo_meta.get('imports', {}).keys())[:8])}",
        "\n**Portfolio Summary:**",
        f"This project is a {repo_meta.get('status')} codebase. It uses {repo_meta.get('language')} and includes features reflected by the main imports: {', '.join(list(repo_meta.get('imports', {}).keys())[:6])}.",
        f"With {repo_meta.get('file_count')} files and {repo_meta.get('loc')} lines of code, it demonstrates a {repo_meta.get('status')} level of completion.",
        "Next steps could include completing unfinished code or enhancing functionality for portfolio readiness."
    ]
    return "\n".join(lines)

# ---------------- full scan ----------------
def run_full_scan(config, progress_callback=None):
    gh_token = config.get("github_token")
    openai_key = config.get("openai_key")
    include_private = config.get("include_private", True)
    output_dir = Path("./codefolio_output/summaries")
    output_dir.mkdir(parents=True, exist_ok=True)

    gh = Github(gh_token)
    repos = gh.get_user().get_repos()
    if not include_private:
        repos = [r for r in repos if not r.private]

    for idx, repo in enumerate(repos):
        send_progress(progress_callback, "scan_repo", int((idx+1)/len(repos)*100), f"Scanning {repo.full_name}")
        meta = analyze_repo(repo, progress_cb=progress_callback)
        summary = ai_summarize(meta, openai_key=openai_key)
        filename = output_dir / f"{repo.name.replace(' ','_')}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(summary)
