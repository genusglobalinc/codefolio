"""
summarizer.py - AI + heuristic hybrid summary generator
"""

import re

try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

KEYWORDS_GUI = ["tkinter", "pygame", "qt", "canvas", "window"]
KEYWORDS_API = ["flask", "fastapi", "express", "routes", "api"]
KEYWORDS_CLI = ["argparse", "sys.argv", "click"]


def generate_summary(meta, files=None, openai_key=None):
    """
    Return a 3-5 sentence portfolio-style summary.
    Uses OpenAI if available, otherwise heuristic fallback.
    """
    files = files or []
    # Try AI first
    if OPENAI_AVAILABLE and openai_key:
        try:
            openai.api_key = openai_key
            prompt = [
                "You are a developer writing a portfolio-quality summary for a GitHub project.",
                f"Project: {meta.get('name')}",
                f"Description: {meta.get('description') or 'No description'}",
                f"Primary language: {meta.get('language')}",
                f"Files: {meta.get('file_count')} | LOC: {meta.get('loc')} | TODOs: {meta.get('todo_count')}",
                "Top imports: " + ", ".join(list(meta.get("imports", {}).keys())[:8]),
            ]
            if files:
                readme_sample = "\n".join([f["content"][:1000] for f in files[:3]])
                prompt.append("\nREADME excerpt:\n" + readme_sample)
            prompt.append("\nWrite a 3-5 sentence portfolio-style summary mentioning tech stack, GUI/API/CLI features, current status, and suggested next steps.")
            resp = openai.Completion.create(
                engine="text-davinci-003",
                prompt="\n".join(prompt),
                temperature=0.18,
                max_tokens=220,
                top_p=1
            )
            return resp.choices[0].text.strip()
        except Exception:
            pass

    # Fallback heuristic
    return heuristic_summary(meta, files)


def heuristic_summary(meta, files):
    # Tech stack
    tech = list(meta.get("imports", {}).keys())[:6]
    ext_stack = list(meta.get("languages_count", {}).keys())[:3]

    tech_stack_str = ", ".join(tech + ext_stack) if tech or ext_stack else "various languages"

    # Determine type
    content = "\n".join([f["content"][:200] for f in files[:5]])
    project_type = "Library/Script"
    if any(k in content.lower() for k in KEYWORDS_GUI):
        project_type = "Desktop GUI"
    elif any(k in content.lower() for k in KEYWORDS_API):
        project_type = "API/Backend"
    elif any(k in content.lower() for k in KEYWORDS_CLI):
        project_type = "CLI Tool"

    # Status
    status = meta.get("status", "Prototype")

    # Next steps
    next_steps = []
    if meta.get("todo_count", 0) > 0:
        next_steps.append("address TODOs")
    if meta.get("file_count", 0) < 5:
        next_steps.append("expand project files")
    if not meta.get("description"):
        next_steps.append("add description/documentation")

    next_steps_str = ", ".join(next_steps) if next_steps else "continue development"

    # Compose summary
    summary = (f"{meta.get('name')} is a {project_type} written in {tech_stack_str}. "
               f"Current status: {status}. "
               f"Next recommended steps: {next_steps_str}.")

    return summary
