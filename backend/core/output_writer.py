"""
output_writer.py - write JSON and Markdown outputs
"""

import json
from pathlib import Path

def write_repo_summary(output_dir, meta, summary_text):
    summaries_dir = Path(output_dir) / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    # Markdown per repo
    filename = summaries_dir / f"{meta['name']}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# {meta['name']}\n\n")
        f.write(f"**Description:** {meta.get('description') or 'No description'}\n\n")
        f.write(f"**Summary:**\n{summary_text}\n\n")
        f.write(f"**Status:** {meta.get('status')}\n")
        f.write(f"**Primary language:** {meta.get('language')}\n")
        f.write(f"**Files:** {meta.get('file_count')} | LOC: {meta.get('loc')} | TODOs: {meta.get('todo_count')}\n")
        f.write(f"**Top imports:** {', '.join(list(meta.get('imports', {}).keys())[:8])}\n")

def write_index(output_dir, all_metadata):
    output_dir = Path(output_dir)
    index_file = output_dir / "index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(all_metadata, f, indent=2)
