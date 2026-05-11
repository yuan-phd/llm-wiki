"""
Team Wiki — Web Server
Run with: python server.py
Then open http://localhost:5001 in your browser.
"""

import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="web", static_url_path="")

client = OpenAI()

# --- Paths ---
WIKI_ROOT = Path(__file__).parent
RAW_DIR = WIKI_ROOT / "raw"
WIKI_DIR = WIKI_ROOT / "wiki"
PROMPTS_DIR = WIKI_ROOT / "_prompts"
UPLOAD_CATEGORIES = ["slack", "meetings", "docs", "code"]

MODEL_HEAVY = "gpt-5.1"          # For compile, ingest, lint — strongest model, best accuracy
MODEL_LIGHT = "gpt-5-mini"       # For ask queries — fast, cheap, good enough for reading compiled wiki

# Supported file extensions for text reading
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".yaml", ".yml"}

# --- Job status tracking ---
jobs = {}


# ====================
# File conversion
# ====================

def convert_docx_to_md(docx_path: Path) -> Path:
    """Convert a .docx file to .md and return the new path."""
    from docx import Document
    doc = Document(str(docx_path))
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        if para.style.name.startswith("Heading 1"):
            lines.append(f"# {text}")
        elif para.style.name.startswith("Heading 2"):
            lines.append(f"## {text}")
        elif para.style.name.startswith("Heading 3"):
            lines.append(f"### {text}")
        else:
            lines.append(text)

    # Also extract tables
    for table in doc.tables:
        lines.append("")
        for i, row in enumerate(table.rows):
            cells = [cell.text.strip() for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
        lines.append("")

    md_path = docx_path.with_suffix(".md")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def convert_pdf_to_md(pdf_path: Path) -> Path:
    """Convert a .pdf file to .md and return the new path."""
    import fitz  # PyMuPDF
    doc = fitz.open(str(pdf_path))
    lines = [f"# {pdf_path.stem}", ""]
    for page_num, page in enumerate(doc, 1):
        text = page.get_text().strip()
        if text:
            lines.append(f"## Page {page_num}")
            lines.append(text)
            lines.append("")
    doc.close()

    md_path = pdf_path.with_suffix(".md")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def convert_file_if_needed(filepath: Path) -> str:
    """
    If file is .docx or .pdf, convert to .md alongside the original.
    Returns status message.
    """
    try:
        if filepath.suffix.lower() == ".docx":
            md_path = convert_docx_to_md(filepath)
            return f"Converted {filepath.name} → {md_path.name}"
        elif filepath.suffix.lower() == ".pdf":
            md_path = convert_pdf_to_md(filepath)
            return f"Converted {filepath.name} → {md_path.name}"
    except Exception as e:
        return f"Conversion failed for {filepath.name}: {e}"
    return ""


# ====================
# Core wiki engine
# ====================

def read_file(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(WIKI_ROOT)
        return f"--- FILE: {rel} ---\n{content}\n"
    except Exception as e:
        return f"--- FILE: {path} (read error: {e}) ---\n"


def read_directory(directory: Path, extensions=None) -> str:
    if extensions is None:
        extensions = TEXT_EXTENSIONS
    contents = []
    for f in sorted(directory.rglob("*")):
        if f.is_file() and f.suffix.lower() in extensions:
            contents.append(read_file(f))
    return "\n".join(contents)


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def call_llm(system_prompt: str, user_content: str, model: str = MODEL_HEAVY, temperature: float = None) -> str:
    print(f"  [LLM] Calling {model} (input ~{len(user_content)} chars)")
    kwargs = {
        "model": model,
        "max_completion_tokens": 32768,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    usage = response.usage
    print(f"  [LLM] Done. Tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out")
    return response.choices[0].message.content


def apply_changes(llm_output: str) -> list:
    """Parse LLM output and write files. Returns list of written paths."""
    written = []
    blocks = llm_output.split("===FILE: ")
    for block in blocks[1:]:
        if "===END===" not in block:
            continue
        header, rest = block.split("===\n", 1)
        filepath = header.strip()
        content = rest.split("===END===")[0].strip()

        target = WIKI_ROOT / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8")
        written.append(filepath)
    return written


# ====================
# API Routes
# ====================

@app.route("/")
def index():
    return send_file("web/index.html")


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload files to raw/ directory. Auto-converts .docx and .pdf to .md."""
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    category = request.form.get("category", "docs")
    if category not in UPLOAD_CATEGORIES:
        category = "docs"

    uploaded = []
    conversions = []
    skipped = []

    for f in request.files.getlist("files"):
        filename = secure_filename(f.filename)
        if not filename:
            continue

        suffix = Path(filename).suffix.lower()

        # Supported formats that the LLM can read
        supported = {".md", ".txt", ".json", ".csv", ".docx", ".pdf", ".yaml", ".yml"}

        if suffix not in supported:
            # Store but flag as not compilable
            dest = RAW_DIR / category / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.save(str(dest))
            skipped.append(f"{category}/{filename} (stored but won't be compiled)")
            continue

        dest = RAW_DIR / category / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(dest))
        uploaded.append(f"{category}/{filename}")

        # Auto-convert docx/pdf to md
        msg = convert_file_if_needed(dest)
        if msg:
            conversions.append(msg)

    result_msg = f"{len(uploaded)} file(s) uploaded to raw/{category}/"
    if conversions:
        result_msg += " | " + ", ".join(conversions)
    if skipped:
        result_msg += " | Skipped: " + ", ".join(skipped)

    return jsonify({
        "status": "ok",
        "uploaded": uploaded,
        "conversions": conversions,
        "skipped": skipped,
        "message": result_msg
    })


@app.route("/api/raw", methods=["GET"])
def list_raw():
    """List all files in raw/."""
    files = []
    for f in sorted(RAW_DIR.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            stat = f.stat()
            files.append({
                "path": str(f.relative_to(RAW_DIR)),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    return jsonify({"files": files})


@app.route("/api/wiki", methods=["GET"])
def list_wiki():
    """List all wiki pages."""
    pages = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if f.name.startswith("_"):
            continue
        rel = str(f.relative_to(WIKI_DIR))
        try:
            content = f.read_text(encoding="utf-8")
            title = rel
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            preview = content[:200]
        except:
            title = rel
            preview = ""
        pages.append({
            "path": rel,
            "title": title,
            "preview": preview,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })
    return jsonify({"pages": pages})


@app.route("/api/wiki/<path:filepath>", methods=["GET"])
def get_wiki_page(filepath):
    """Read a specific wiki page. Auto-converts legacy link formats."""
    target = WIKI_DIR / filepath
    if not target.exists() or not target.is_file():
        return jsonify({"error": "Page not found"}), 404
    content = target.read_text(encoding="utf-8")

    import re
    # Convert __filename.md__ patterns to [[links]]
    def convert_legacy_link(match):
        filename = match.group(1)
        # Search wiki for this filename
        for f in WIKI_DIR.rglob(f"{filename}.md"):
            rel = str(f.relative_to(WIKI_DIR))[:-3]
            title = filename
            try:
                for line in f.read_text(encoding="utf-8").split("\n"):
                    if line.startswith("title:"):
                        title = line.split("title:", 1)[1].strip()
                        break
            except:
                pass
            return f"[[{rel}|{title}]]"
        return filename  # Not found, just return plain text

    content = re.sub(r'__([a-z0-9-]+(?:\.[a-z]+)?)__', convert_legacy_link, content)

    return jsonify({"path": filepath, "content": content})




@app.route("/api/wiki/summary", methods=["GET"])
def get_status():
    """Return the auto-generated status summary."""
    status_path = WIKI_DIR / "_summary.md"
    if status_path.exists():
        content = status_path.read_text(encoding="utf-8")
        # Extract last_updated from first line if present
        last_updated = ""
        for line in content.split("\n"):
            if line.startswith("<!-- updated:"):
                last_updated = line.replace("<!-- updated:", "").replace("-->", "").strip()
                break
        return jsonify({"content": content, "last_updated": last_updated})
    return jsonify({"content": "No status generated yet. Run Compile or Ingest first.", "last_updated": ""})


@app.route("/api/wiki/nav")
def get_wiki_nav():
    nav_path = WIKI_DIR / "_nav.md"
    if nav_path.exists():
        return jsonify({"content": nav_path.read_text(encoding="utf-8")})
    return jsonify({"content": ""})


@app.route("/api/wiki/graph")
def get_wiki_graph():
    """Extract nodes and edges from wiki pages for graph visualization."""
    import re
    nodes = []
    edges = []

    # Determine group for each page based on its folder
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if f.name.startswith("_"):
            continue
        rel = str(f.relative_to(WIKI_DIR))
        rel_no_ext = rel[:-3]
        folder = rel.split("/")[0] if "/" in rel else "other"

        title = f.stem.replace("-", " ").title()
        try:
            for line in f.read_text(encoding="utf-8").split("\n"):
                if line.startswith("title:"):
                    title = line.split("title:", 1)[1].strip()
                    break
        except:
            pass

        nodes.append({"id": rel_no_ext, "title": title, "group": folder})

        # Extract [[links]] from content
        try:
            content = f.read_text(encoding="utf-8")
            links = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', content)
            for link in links:
                target = link.strip()
                if target.endswith(".md"):
                    target = target[:-3]
                # Only add edge if target exists as a node
                edges.append({"source": rel_no_ext, "target": target})
        except:
            pass

    # Filter edges to only include existing nodes
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]
    # Deduplicate edges
    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    return jsonify({"nodes": nodes, "edges": unique_edges})


@app.route("/api/wiki/save_answer", methods=["POST"])
def save_answer():
    """Save an Ask answer as a wiki page."""
    data = request.json
    question = data.get("question", "").strip()
    answer = data.get("answer", "").strip()
    if not question or not answer:
        return jsonify({"error": "Question and answer required"}), 400

    # Generate filename from question
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', question.lower()).strip('-')[:60]
    timestamp = datetime.now().strftime("%Y-%m-%d")
    filename = f"queries/{timestamp}-{slug}.md"

    # Create the page
    filepath = WIKI_DIR / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)

    content = f"""---
title: "{question}"
last_updated: {timestamp}
type: query
---

# {question}

{answer}
"""
    filepath.write_text(content, encoding="utf-8")

    # Add to navigation
    nav_path = WIKI_DIR / "_nav.md"
    if nav_path.exists():
        nav_content = nav_path.read_text(encoding="utf-8")
        nav_entry = f'\n- [[{filename[:-3]}|{question}]]'
        if "## Saved Queries" in nav_content:
            nav_content = nav_content.replace("## Saved Queries", f"## Saved Queries{nav_entry}")
        else:
            nav_content += f'\n\n## Saved Queries{nav_entry}'
        nav_path.write_text(nav_content, encoding="utf-8")

    return jsonify({"status": "ok", "path": filename, "message": f"Saved as {filename}"})


def generate_summary():
    """Auto-generate project status summary and save as _summary.md."""
    print("  [Status] Generating project status summary...")
    wiki_content = read_directory(WIKI_DIR)

    system = "Write a short project status dashboard. Maximum 15 lines total. For each major topic, write ONE line: topic name — status (done/in-progress/pending/blocked) and a few words of context. This is for a manager to glance at in 10 seconds. No detailed explanations. No 'open/pending' subsections. No technical implementation details. No people lists. Output clean markdown with bullet points."

    summary_path = WIKI_DIR / "_summary.md"
    if summary_path.exists():
        existing = summary_path.read_text(encoding="utf-8")
        user_msg = f"Here is the current summary. Update it with any new information but keep the same format and number of lines. Do not add new topics unless something genuinely new appeared. Do not remove topics.\n\n{existing}\n\nHere is the team wiki:\n\n{wiki_content}"
    else:
        user_msg = f"Here is the team wiki:\n\n{wiki_content}"

    try:
        result = call_llm(system, user_msg, model=MODEL_LIGHT)
        # Prepend update timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        status_content = f"<!-- updated: {timestamp} -->\n{result}"
        status_path = WIKI_DIR / "_summary.md"
        status_path.write_text(status_content, encoding="utf-8")
        print(f"  [Status] Saved to _summary.md ({len(result)} chars)")
    except Exception as e:
        print(f"  [Status] Failed: {e}")


def generate_nav(preserve_structure=False):
    """Generate wiki/_nav.md — LLM-organized navigation structure."""
    print("  [Nav] Generating navigation...")
    page_list = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if f.name.startswith("_") or f.name == "README.md":
            continue
        rel = str(f.relative_to(WIKI_DIR))[:-3]  # remove .md
        title = f.stem.replace("-", " ").title()
        try:
            for line in f.read_text(encoding="utf-8").split("\n"):
                if line.startswith("title:"):
                    title = line.split("title:", 1)[1].strip()
                    break
        except:
            pass
        page_list.append(f"- {rel}: {title}")

    pages_text = "\n".join(page_list)

    system = "Organize these wiki pages into a navigation structure. Group related pages together. You decide the groups and order. Format:\n\n## [Group Name]\n- [[page-path|Page Title]]\n\nUse ## headings for groups and - [[links]] for pages. Output only the navigation markdown, nothing else. Keep Projects and Systems as separate groups. Do not merge them. Sort Meetings and Saved Queries sections in descending date order (newest first). If sub-topic pages exist alongside a main project page, group them under the same Projects section rather than creating a separate group."

    nav_path = WIKI_DIR / "_nav.md"
    if preserve_structure and nav_path.exists():
        existing_nav = nav_path.read_text(encoding="utf-8")
        user_msg = f"Here is the current navigation. Keep all existing groups and their pages unchanged. If new pages fit an existing group, add them there. If new pages belong to a clearly different project or topic that has no existing group, create a new ## group for them. Do not remove, rename, or reorganize any existing entries.\n\n{existing_nav}\n\nWiki pages:\n{pages_text}"
    else:
        user_msg = f"Wiki pages:\n{pages_text}"

    try:
        result = call_llm(system, user_msg, model=MODEL_LIGHT)
        nav_path = WIKI_DIR / "_nav.md"
        nav_path.write_text(result, encoding="utf-8")
        print(f"  [Nav] Saved to _nav.md")
    except Exception as e:
        print(f"  [Nav] Failed: {e}")


@app.route("/api/ask", methods=["POST"])
def ask_question():
    """Ask a question against the wiki."""
    data = request.json
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    system = "You are a knowledgeable team assistant. Answer questions based on the wiki content provided. Be direct and specific, but explain connections and context when relevant. Cite wiki pages using [[page-name]] when referencing information. If the answer is not in the wiki, say so clearly. Do NOT offer follow-up suggestions or say 'if you want, I can' or 'would you like me to'. Just answer the question."

    # Step 1 (L1 — routing): select relevant pages
    pages = []
    try:
        summary = (WIKI_DIR / "_summary.md").read_text(encoding="utf-8") if (WIKI_DIR / "_summary.md").exists() else ""
        nav = (WIKI_DIR / "_nav.md").read_text(encoding="utf-8") if (WIKI_DIR / "_nav.md").exists() else ""
        print(f"  [Ask L1] Routing: {len(summary + nav)} chars")
        routing_prompt = (
            f"Here is the wiki summary:\n\n{summary}\n\n"
            f"Here is the wiki navigation:\n\n{nav}\n\n"
            f"Question: {question}\n\n"
            'Based on this wiki summary and navigation, which wiki pages are most relevant to answer this question? '
            'Return ONLY a JSON list of file paths, like: ["meetings/weekly-checkin-2026-03-27.md", "people/john-doe.md"]. '
            'Select ONLY the pages directly needed to answer this question. Be selective — fewer is better. Guidelines:\n- Question about a specific person: select their person page PLUS 2-3 pages they are linked to (projects, meetings, decisions).\n- Question about a specific topic or decision: 2-4 pages.\n- Broad question (status, blockers, overview): 5-8 pages.\nNever select more than 8. Return only the JSON array of file paths, nothing else.'
        )
        raw = call_llm("You are a routing assistant.", routing_prompt, model=MODEL_LIGHT)
        import json as _json
        pages = _json.loads(raw.strip())
        if not isinstance(pages, list):
            pages = []
        print(f"  [Ask L1] Selected {len(pages)} pages")
    except Exception:
        pages = []

    # Step 2 (L2 — answer): read selected pages or fall back to full wiki
    if pages:
        parts = []
        for p in pages:
            fp = WIKI_DIR / p
            if fp.exists():
                parts.append(f"### {p}\n{fp.read_text(encoding='utf-8')}")
        selected_content = "\n\n".join(parts)
        print(f"  [Ask L2] Reading {len(selected_content)} chars")
        if not selected_content:
            selected_content = read_directory(WIKI_DIR)
    else:
        selected_content = read_directory(WIKI_DIR)
        print(f"  [Ask L2] Reading {len(selected_content)} chars")

    user_msg = f"Here is the team wiki:\n\n{selected_content}\n\nQuestion: {question}"

    answer = call_llm(system, user_msg, model=MODEL_LIGHT)

    return jsonify({"answer": answer})


def linkify_md_references(text: str) -> str:
    """
    Convert ALL wiki references to [[path|title]] format.
    Catches: [[filename.md|display]], bare filename.md, and plain display names like "John Doe".
    """
    import re

    # Build lookup of all wiki pages
    wiki_files = {}   # "john-doe.md" → (path, title)
    wiki_stems = {}   # "john-doe" → (path, title)
    wiki_titles = {}  # "John Doe" → (path, title)

    for f in WIKI_DIR.rglob("*.md"):
        if f.name.startswith("_"):
            continue
        filename = f.name
        stem = f.stem
        rel = str(f.relative_to(WIKI_DIR))[:-3]
        title = stem.replace("-", " ").title()
        try:
            for line in f.read_text(encoding="utf-8").split("\n"):
                if line.startswith("title:"):
                    title = line.split("title:", 1)[1].strip()
                    break
        except:
            pass
        wiki_files[filename] = (rel, title)
        wiki_stems[stem] = (rel, title)
        wiki_titles[title] = (rel, title)

    # Step 1: Fix any existing [[links]] that contain .md filenames
    def fix_bracket_link(match):
        inner = match.group(1)
        if '|' in inner:
            path_part, display = inner.split('|', 1)
        else:
            path_part = inner
            display = None
        path_part = path_part.strip()
        # Try resolving
        for lookup in [wiki_files, wiki_stems]:
            key = path_part.replace('.md', '') if path_part.endswith('.md') else path_part
            last = key.split('/')[-1]
            if key in lookup:
                p, t = lookup[key]
                return f'[[{p}|{display.strip() if display else t}]]'
            if last in lookup:
                p, t = lookup[last]
                return f'[[{p}|{display.strip() if display else t}]]'
        return match.group(0)

    text = re.sub(r'\[\[([^\]]+)\]\]', fix_bracket_link, text)

    # Step 2: Protect all [[links]] we just fixed
    protected = []
    def protect(m):
        protected.append(m.group(0))
        return f'\x00P{len(protected)-1}\x00'
    text = re.sub(r'\[\[[^\]]+\]\]', protect, text)

    # Step 3: Replace bare filename.md references
    def replace_bare_md(match):
        filename = match.group(0)
        if filename in wiki_files:
            path, title = wiki_files[filename]
            return f'[[{path}|{title}]]'
        return filename
    text = re.sub(r'[a-zA-Z0-9_-]+\.md', replace_bare_md, text)

    # Step 4: Replace display name references (e.g. "John Doe", "Example Project")
    # Sort by length (longest first) to prevent partial matches
    sorted_titles = sorted(wiki_titles.keys(), key=len, reverse=True)
    for title in sorted_titles:
        path, display = wiki_titles[title]
        # Skip very short titles (< 4 chars) to avoid false matches
        if len(title) < 4:
            continue
        # Case-sensitive match for proper names
        if title in text:
            text = text.replace(title, f'[[{path}|{display}]]')

    # Step 5: Restore protected links
    for i, link in enumerate(protected):
        text = text.replace(f'\x00P{i}\x00', link)

    # Clean up: remove any double [[ or ]]
    # If a title got replaced inside an already-protected link, fix it
    text = re.sub(r'\[\[([^\]]*)\[\[([^\]|]+)\|([^\]]+)\]\]([^\]]*)\]\]', 
                  lambda m: f'[[{m.group(2)}|{m.group(3)}]]', text)

    return text


def auto_link_wiki_references(text: str) -> str:
    """
    Scan text for any wiki page names/titles and convert to [[path|title]] links.
    """
    import re

    # Build lookup of all matchable strings → (wiki_path, display_title)
    matches = {}  # matchable_string → (path, title)

    for f in sorted(WIKI_DIR.rglob("*.md")):
        if f.name.startswith("_") or f.name == "README.md":
            continue
        rel = str(f.relative_to(WIKI_DIR))
        rel_no_ext = rel[:-3]
        filename = f.stem  # e.g. "john-doe"

        # Extract title from frontmatter
        title = None
        try:
            content = f.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("title:"):
                    title = line.split("title:", 1)[1].strip()
                    break
        except:
            pass

        # Generate human-readable name from filename: "john-doe" → "John Doe"
        human_name = filename.replace("-", " ").title()

        # Add all matchable variants
        # 1. filename.md (e.g. "john-doe.md")
        matches[filename + ".md"] = (rel_no_ext, title or human_name)
        # 2. bare filename (e.g. "john-doe")
        matches[filename] = (rel_no_ext, title or human_name)
        # 3. human-readable from filename (e.g. "John Doe")
        matches[human_name] = (rel_no_ext, title or human_name)
        # 4. actual title if different (e.g. "John Doe" or "Example Project")
        if title and title != human_name:
            matches[title] = (rel_no_ext, title)

    # Sort by length (longest first) to avoid partial matches
    sorted_keys = sorted(matches.keys(), key=len, reverse=True)
    print(f"  [AutoLink] {len(sorted_keys)} matchable names: {sorted_keys[:10]}...")

    # Step 1: Protect existing [[links]]
    protected = []
    def protect(m):
        protected.append(m.group(0))
        return f'\x00LINK{len(protected)-1}\x00'
    text = re.sub(r'\[\[[^\]]+\]\]', protect, text)

    # Step 2: Replace all matchable strings with [[links]]
    for key in sorted_keys:
        path, title = matches[key]
        if " " in key or key[0].isupper():
            pattern = re.compile(re.escape(key), re.IGNORECASE)
        else:
            pattern = re.compile(r'\b' + re.escape(key) + r'\b')

        replacement = f'[[{path}|{title}]]'
        new_text = pattern.sub(replacement, text)

        # If we made replacements, protect the new [[links]] to prevent nesting
        if new_text != text:
            text = new_text
            def re_protect(m):
                protected.append(m.group(0))
                return f'\x00LINK{len(protected)-1}\x00'
            text = re.sub(r'\[\[[^\]]+\]\]', re_protect, text)

    # Step 3: Restore protected links
    for i, link in enumerate(protected):
        text = text.replace(f'\x00LINK{i}\x00', link)

    # Clean up double brackets
    text = text.replace('[[[[', '[[').replace(']]]]', ']]')

    return text


# ====================
# People Management
# ====================

def append_log(operation_type: str, details: str):
    """Append an entry to wiki/_log.md."""
    log_path = WIKI_DIR / "_log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## [{timestamp}] {operation_type}\n{details}\n"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
    else:
        content = "# Wiki Log\n\nAppend-only record of wiki operations.\n"
    content += entry
    log_path.write_text(content, encoding="utf-8")


def load_aliases() -> dict:
    """Load _aliases.json, return dict."""
    path = WIKI_DIR / "_aliases.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"description": "Name aliases config.", "aliases": []}


def save_aliases(data: dict):
    """Write _aliases.json."""
    path = WIKI_DIR / "_aliases.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rewrite_links_in_wiki(old_link: str, new_link: str, old_display: str = None, new_display: str = None):
    """
    Find and replace wiki links across ALL wiki .md files.
    Handles patterns like:
      [[people/old-name]]
      [[people/old-name|Display Name]]
    """
    count = 0
    for f in WIKI_DIR.rglob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            original = content

            # Replace [[people/old-name|anything]] → [[people/new-name|new display]]
            import re
            pattern = re.escape(f"[[{old_link}")
            # Match [[old-link]] or [[old-link|display]]
            content = re.sub(
                r'\[\[' + re.escape(old_link) + r'(?:\|[^\]]+)?\]\]',
                f'[[{new_link}|{new_display or new_link.split("/")[-1]}]]',
                content
            )

            # Also replace plain text references to old display name
            if old_display and new_display and old_display != new_display:
                content = content.replace(old_display, new_display)

            if content != original:
                f.write_text(content, encoding="utf-8")
                count += 1
        except:
            pass
    return count


def remove_links_in_wiki(link: str):
    """Remove all [[link]] references, replacing with plain text."""
    count = 0
    for f in WIKI_DIR.rglob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
            original = content
            import re
            # [[people/name|Display]] → Display, [[people/name]] → name
            content = re.sub(
                r'\[\[' + re.escape(link) + r'\|([^\]]+)\]\]',
                r'\1',
                content
            )
            content = re.sub(
                r'\[\[' + re.escape(link) + r'\]\]',
                link.split("/")[-1],
                content
            )
            if content != original:
                f.write_text(content, encoding="utf-8")
                count += 1
        except:
            pass
    return count


@app.route("/api/people", methods=["GET"])
def list_people():
    """List all people pages with their content summary."""
    people_dir = WIKI_DIR / "people"
    if not people_dir.exists():
        return jsonify({"people": []})

    people = []
    for f in sorted(people_dir.glob("*.md")):
        if f.name == "README.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
            title = f.stem
            sources = []
            for line in content.split("\n"):
                if line.startswith("title:"):
                    title = line.split("title:")[1].strip()
                elif line.strip().startswith("- raw/"):
                    sources.append(line.strip()[2:])
            people.append({
                "filename": f.stem,
                "title": title,
                "sources": sources,
                "path": f"people/{f.name}"
            })
        except:
            pass
    return jsonify({"people": people})


@app.route("/api/people/merge", methods=["POST"])
def merge_people():
    """
    Merge person B into person A.
    - Combines content from both pages into A
    - Deletes B's page
    - Updates all wiki links pointing to B → A
    - Adds B as an alias in _aliases.json
    """
    data = request.json
    keep = data.get("keep", "").strip()       # filename to keep (e.g. "jane-doe")
    remove = data.get("remove", "").strip()   # filename to merge in and delete

    if not keep or not remove:
        return jsonify({"error": "Must provide 'keep' and 'remove' filenames"}), 400

    keep_path = WIKI_DIR / "people" / f"{keep}.md"
    remove_path = WIKI_DIR / "people" / f"{remove}.md"

    if not keep_path.exists():
        return jsonify({"error": f"Person '{keep}' not found"}), 404
    if not remove_path.exists():
        return jsonify({"error": f"Person '{remove}' not found"}), 404

    # Read both files
    keep_content = keep_path.read_text(encoding="utf-8")
    remove_content = remove_path.read_text(encoding="utf-8")

    # Extract title from the removed page
    remove_title = remove
    for line in remove_content.split("\n"):
        if line.startswith("title:"):
            remove_title = line.split("title:")[1].strip()
            break

    keep_title = keep
    for line in keep_content.split("\n"):
        if line.startswith("title:"):
            keep_title = line.split("title:")[1].strip()
            break

    # Append unique info from removed page to kept page
    # Add "Also known as" section if not present
    if "Also known as" not in keep_content:
        keep_content = keep_content.rstrip() + f"\n\n## Also Known As\n- {remove_title}\n"
    else:
        keep_content = keep_content.rstrip() + f"\n- {remove_title}\n"

    # Append any sources from removed page that aren't in kept page
    for line in remove_content.split("\n"):
        if line.strip().startswith("- raw/") and line.strip() not in keep_content:
            # Find sources section in keep_content and append
            if "sources:" in keep_content:
                idx = keep_content.index("sources:")
                end_of_sources = keep_content.index("\n---", idx) if "\n---" in keep_content[idx:] else len(keep_content)
                keep_content = keep_content[:end_of_sources].rstrip() + "\n  " + line.strip() + "\n" + keep_content[end_of_sources:]

    # Save updated keep file
    keep_path.write_text(keep_content, encoding="utf-8")

    # Delete removed file
    remove_path.unlink()

    # Rewrite all links across wiki
    files_updated = rewrite_links_in_wiki(
        f"people/{remove}", f"people/{keep}",
        remove_title, keep_title
    )

    # Update _aliases.json
    aliases = load_aliases()
    # Check if keep already has an alias entry
    found = False
    for entry in aliases["aliases"]:
        if entry["canonical_filename"] == keep:
            if remove_title not in entry["variants"]:
                entry["variants"].append(remove_title)
            if remove not in [v.lower().replace(" ", "-") for v in entry["variants"]]:
                entry["variants"].append(remove.replace("-", " ").title())
            found = True
            break
    if not found:
        aliases["aliases"].append({
            "canonical_name": keep_title,
            "canonical_filename": keep,
            "variants": [remove_title, remove.replace("-", " ").title()]
        })
    save_aliases(aliases)

    return jsonify({
        "status": "ok",
        "message": f"Merged '{remove_title}' into '{keep_title}'. Updated {files_updated} wiki files.",
        "files_updated": files_updated
    })


@app.route("/api/people/delete", methods=["POST"])
def delete_person():
    """Delete a person page and clean up all references."""
    data = request.json
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"error": "Must provide 'filename'"}), 400

    filepath = WIKI_DIR / "people" / f"{filename}.md"
    if not filepath.exists():
        return jsonify({"error": f"Person '{filename}' not found"}), 404

    # Get title before deleting
    content = filepath.read_text(encoding="utf-8")
    title = filename
    for line in content.split("\n"):
        if line.startswith("title:"):
            title = line.split("title:")[1].strip()
            break

    # Delete the file
    filepath.unlink()

    # Remove all links to this person across wiki
    files_updated = remove_links_in_wiki(f"people/{filename}")

    return jsonify({
        "status": "ok",
        "message": f"Deleted '{title}'. Cleaned references in {files_updated} files.",
        "files_updated": files_updated
    })


@app.route("/api/people/rename", methods=["POST"])
def rename_person():
    """Rename a person — updates filename, title, all references, and aliases."""
    data = request.json
    old_filename = data.get("old_filename", "").strip()
    new_name = data.get("new_name", "").strip()

    if not old_filename or not new_name:
        return jsonify({"error": "Must provide 'old_filename' and 'new_name'"}), 400

    old_path = WIKI_DIR / "people" / f"{old_filename}.md"
    if not old_path.exists():
        return jsonify({"error": f"Person '{old_filename}' not found"}), 404

    # Generate new filename from new name
    import unicodedata
    new_filename = new_name.lower()
    # Replace umlauts
    replacements = {"ö": "oe", "ü": "ue", "ä": "ae", "ß": "ss", "é": "e", "è": "e", "ê": "e", "à": "a", "â": "a"}
    for old_char, new_char in replacements.items():
        new_filename = new_filename.replace(old_char, new_char)
    new_filename = "".join(c if c.isalnum() or c == " " else "" for c in new_filename)
    new_filename = new_filename.strip().replace(" ", "-")

    new_path = WIKI_DIR / "people" / f"{new_filename}.md"

    # Read and update content
    content = old_path.read_text(encoding="utf-8")

    # Get old title
    old_title = old_filename
    for line in content.split("\n"):
        if line.startswith("title:"):
            old_title = line.split("title:")[1].strip()
            break

    # Replace title in content
    content = content.replace(f"title: {old_title}", f"title: {new_name}")

    # Write new file
    new_path.write_text(content, encoding="utf-8")

    # Delete old file (if different name)
    if old_path != new_path:
        old_path.unlink()

    # Update all links
    files_updated = rewrite_links_in_wiki(
        f"people/{old_filename}", f"people/{new_filename}",
        old_title, new_name
    )

    # Update aliases
    aliases = load_aliases()
    found = False
    for entry in aliases["aliases"]:
        if entry["canonical_filename"] == old_filename:
            entry["canonical_name"] = new_name
            entry["canonical_filename"] = new_filename
            if old_title not in entry["variants"]:
                entry["variants"].append(old_title)
            found = True
            break
    if not found and old_filename != new_filename:
        aliases["aliases"].append({
            "canonical_name": new_name,
            "canonical_filename": new_filename,
            "variants": [old_title]
        })
    save_aliases(aliases)

    return jsonify({
        "status": "ok",
        "message": f"Renamed '{old_title}' → '{new_name}'. Updated {files_updated} wiki files.",
        "files_updated": files_updated
    })


import time

# Rough token estimate: ~4 chars per token
MAX_TOKENS_PER_BATCH = 25000  # gpt-5-mini allows 500K TPM, stay well within
MAX_TOKENS_PER_FILE = 50000    # Truncate individual files that exceed this
BATCH_DELAY_SECONDS = 65       # Wait between batches if needed


def estimate_tokens(text: str) -> int:
    """Rough token estimate."""
    return len(text) // 4


def get_raw_files() -> list:
    """Get all readable raw files as (path, content) pairs. Truncates oversized files."""
    files = []
    for f in sorted(RAW_DIR.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT_EXTENSIONS:
            try:
                content = read_file(f)
                tokens = estimate_tokens(content)
                if tokens > MAX_TOKENS_PER_FILE:
                    # Truncate and add a note
                    char_limit = MAX_TOKENS_PER_FILE * 4
                    truncated = content[:char_limit]
                    truncated += f"\n\n[... FILE TRUNCATED — original was ~{tokens} tokens, showing first ~{MAX_TOKENS_PER_FILE} tokens ...]\n"
                    files.append((f, truncated))
                    print(f"  [Warning] Truncated {f.name}: {tokens} tokens → ~{MAX_TOKENS_PER_FILE} tokens")
                else:
                    files.append((f, content))
            except:
                pass
    return files


def batch_files(files: list, max_tokens: int) -> list:
    """Group files into batches that fit within token limit."""
    batches = []
    current_batch = []
    current_tokens = 0
    for filepath, content in files:
        tokens = estimate_tokens(content)
        if current_tokens + tokens > max_tokens and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append((filepath, content))
        current_tokens += tokens
    if current_batch:
        batches.append(current_batch)
    return batches


def run_job(job_id: str, job_type: str):
    """Run a wiki job in background. Processes files in batches to respect API rate limits."""
    try:
        jobs[job_id]["status"] = "running"
        all_written = []
        all_changelogs = []

        if job_type == "compile":
            # Clean existing wiki pages before full rebuild (keep _schema, _index, _aliases)
            for f in WIKI_DIR.rglob("*.md"):
                if not f.name.startswith("_"):
                    f.unlink()
            print("  [Compile] Cleaned old wiki pages.")

            schema = read_file(WIKI_DIR / "_schema.md")
            aliases = ""
            if (WIKI_DIR / "_aliases.json").exists():
                aliases = read_file(WIKI_DIR / "_aliases.json")
            raw_files = get_raw_files()
            batches = batch_files(raw_files, MAX_TOKENS_PER_BATCH)
            total_batches = len(batches)

            print(f"  [Compile] {len(raw_files)} files → {total_batches} batch(es)")

            for i, batch in enumerate(batches, 1):
                jobs[job_id]["result"] = {
                    "progress": f"Processing batch {i}/{total_batches}..."
                }

                batch_content = "\n".join(content for _, content in batch)

                # After first batch, send only a brief index of what exists (not full content)
                wiki_context = ""
                if i > 1:
                    existing_pages = []
                    for f in sorted(WIKI_DIR.rglob("*.md")):
                        if f.name.startswith("_"):
                            continue
                        try:
                            content_text = f.read_text(encoding="utf-8")
                            first_line = ""
                            for line in content_text.split("\n"):
                                if line.startswith("# "):
                                    first_line = line
                                    break
                            rel = str(f.relative_to(WIKI_DIR))
                            existing_pages.append(f"  - {rel}: {first_line}")
                        except:
                            pass
                    if existing_pages:
                        wiki_context = "\n\nWiki pages already created (do NOT duplicate, create new pages or extend if related):\n" + "\n".join(existing_pages)

                prompt = load_prompt("compile_full")
                user_msg = f"""Here is the wiki schema:\n\n{schema}\n\nHere is the name aliases config (you MUST follow this strictly — one page per person, use canonical names everywhere):\n\n{aliases}\n\nHere are the raw source files (batch {i}/{total_batches}):\n\n{batch_content}{wiki_context}\n\n
Please compile wiki pages from these sources. Output every file using this exact format:\n\n===FILE: wiki/path/to/file.md===\n(full file content here)\n===END===\n\nThen provide a brief summary of what you created."""

                result = call_llm(prompt, user_msg, model=MODEL_HEAVY)
                written = apply_changes(result)
                all_written.extend(written)

                changelog = result.split("===END===")[-1].strip()
                if changelog:
                    all_changelogs.append(f"Batch {i}: {changelog}")

                print(f"  [Compile] Batch {i}/{total_batches} done. {len(written)} files written.")

                # Wait between batches to respect TPM rate limit
                if i < total_batches:
                    print(f"  [Compile] Waiting {BATCH_DELAY_SECONDS}s for rate limit reset...")
                    time.sleep(BATCH_DELAY_SECONDS)

            jobs[job_id]["result"] = {
                "files_written": all_written,
                "changelog": "\n\n".join(all_changelogs)
            }
            append_log("compile", f"{len(all_written)} files written.\n" + "\n".join(all_changelogs))

            # Auto-generate status summary
            generate_summary()
            generate_nav(preserve_structure=False)

        elif job_type == "ingest":
            raw_files = get_raw_files()
            batches = batch_files(raw_files, MAX_TOKENS_PER_BATCH)
            total_batches = len(batches)

            print(f"  [Ingest] {len(raw_files)} files → {total_batches} batch(es)")

            for i, batch in enumerate(batches, 1):
                jobs[job_id]["result"] = {
                    "progress": f"Processing batch {i}/{total_batches}..."
                }

                batch_content = "\n".join(content for _, content in batch)

                # Send brief wiki index, not full content
                existing_pages = []
                for f in sorted(WIKI_DIR.rglob("*.md")):
                    if f.name.startswith("_"):
                        continue
                    try:
                        ct = f.read_text(encoding="utf-8")
                        first_line = ""
                        for line in ct.split("\n"):
                            if line.startswith("# "):
                                first_line = line
                                break
                        rel = str(f.relative_to(WIKI_DIR))
                        existing_pages.append(f"  - {rel}: {first_line}")
                    except:
                        pass
                wiki_index = "\n".join(existing_pages) if existing_pages else "(empty wiki)"

                prompt = load_prompt("ingest")
                aliases = ""
                if (WIKI_DIR / "_aliases.json").exists():
                    aliases = read_file(WIKI_DIR / "_aliases.json")
                user_msg = f"""Name aliases (MUST follow strictly):\n{aliases}\n\nExisting wiki pages (do NOT duplicate, update or create new as needed):\n{wiki_index}\n\nHere are the raw source files to integrate (batch {i}/{total_batches}):\n\n{batch_content}\n\n
Please output all new or updated wiki files using this exact format:\n\n===FILE: wiki/path/to/file.md===\n(full file content here)\n===END===\n\nThen provide a changelog summary."""

                result = call_llm(prompt, user_msg, model=MODEL_HEAVY)
                written = apply_changes(result)
                all_written.extend(written)

                changelog = result.split("===END===")[-1].strip()
                if changelog:
                    all_changelogs.append(f"Batch {i}: {changelog}")

                print(f"  [Ingest] Batch {i}/{total_batches} done. {len(written)} files written.")

                if i < total_batches:
                    print(f"  [Ingest] Waiting {BATCH_DELAY_SECONDS}s for rate limit reset...")
                    time.sleep(BATCH_DELAY_SECONDS)

            jobs[job_id]["result"] = {
                "files_written": all_written,
                "changelog": "\n\n".join(all_changelogs)
            }
            append_log("ingest", f"{len(all_written)} files written.\n" + "\n".join(all_changelogs))

            # Auto-generate status summary
            generate_summary()
            generate_nav(preserve_structure=True)

        elif job_type == "lint":
            prompt = load_prompt("lint")
            wiki_content = read_directory(WIKI_DIR)

            # Lint might also be too large — truncate if needed
            if estimate_tokens(wiki_content) > MAX_TOKENS_PER_BATCH:
                # Just send page summaries instead of full content
                summaries = []
                for f in sorted(WIKI_DIR.rglob("*.md")):
                    if f.name.startswith("_"):
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                        # Take first 500 chars of each page
                        rel = str(f.relative_to(WIKI_DIR))
                        summaries.append(f"--- {rel} ---\n{content[:500]}\n")
                    except:
                        pass
                wiki_content = "\n".join(summaries)

            user_msg = f"Here is the full wiki content:\n\n{wiki_content}\n\nPlease perform a health check and return your report in markdown."
            result = call_llm(prompt, user_msg, model=MODEL_HEAVY)
            jobs[job_id]["result"] = {"report": result}
            append_log("lint", result[:500])

        jobs[job_id]["status"] = "done"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["result"] = {"error": str(e)}


@app.route("/api/run/refresh_summary", methods=["POST"])
def refresh_summary():
    """Regenerate summary without running compile or ingest."""
    try:
        generate_summary()
        return jsonify({"status": "ok", "message": "Summary refreshed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run/<job_type>", methods=["POST"])
def start_job(job_type):
    """Start a compile/ingest/lint job."""
    if job_type not in ("compile", "ingest", "lint"):
        return jsonify({"error": "Invalid job type"}), 400

    # Check if a job is already running
    for jid, j in jobs.items():
        if j["status"] == "running":
            return jsonify({"error": "A job is already running", "job_id": jid}), 409

    job_id = f"{job_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    jobs[job_id] = {
        "type": job_type,
        "status": "queued",
        "started": datetime.now().isoformat(),
        "result": None
    }

    thread = threading.Thread(target=run_job, args=(job_id, job_type))
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/job/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Check status of a running job."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job_id": job_id, **jobs[job_id]})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get wiki statistics."""
    raw_count = sum(1 for f in RAW_DIR.rglob("*") if f.is_file() and not f.name.startswith("."))
    wiki_count = sum(1 for f in WIKI_DIR.rglob("*.md") if not f.name.startswith("_"))
    wiki_words = 0
    for f in WIKI_DIR.rglob("*.md"):
        try:
            wiki_words += len(f.read_text(encoding="utf-8").split())
        except:
            pass
    return jsonify({
        "raw_files": raw_count,
        "wiki_pages": wiki_count,
        "wiki_words": wiki_words,
    })


if __name__ == "__main__":
    # Ensure directories exist
    for cat in UPLOAD_CATEGORIES:
        (RAW_DIR / cat).mkdir(parents=True, exist_ok=True)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    print("\n  Team Wiki is running at http://localhost:5001")
    print(f"  Models: compile/ingest/lint → {MODEL_HEAVY} | ask → {MODEL_LIGHT}")
    print(f"  Supported uploads: .md .txt .json .csv .docx .pdf")
    print(f"  (png/images stored but not compiled)\n")
    app.run(host="0.0.0.0", port=5001, debug=True)
