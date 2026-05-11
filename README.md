# LLM Wiki

An LLM-powered knowledge base that compiles scattered documents into a structured, searchable wiki. Based on [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern.

Everyone interacts through a web UI — no command line needed for daily use.

## Features
- **Browse Wiki** — structured navigation with project summary dashboard and status badges
- **Ask** — question answering with L1/L2 cache (80%+ token savings)
- **Graph** — interactive force-directed graph showing page connections
- **Upload** — drag-and-drop file upload with auto-conversion (docx, pdf)
- **People** — manage team members with merge, rename, delete
- **Save answers** — save valuable Ask results back into the wiki
- **Obsidian compatible** — open wiki/ as an Obsidian vault for graph view and backlinks

---

## Setup (One-time, on your build machine)

### 1. Clone and install

```bash
git clone <your-repo-url> llm-wiki
cd llm-wiki
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add your API key

```bash
cp .env.example .env
# Edit .env and paste your OpenAI API key
```

### 3. Start the server

```bash
python server.py
```

Open **http://localhost:5001** in your browser. That's it.

---

## How Your Team Uses It

### Upload sources
1. Open the web UI → **Upload** tab
2. Pick a category (docs / slack / meetings / code)
3. Drag and drop files

### Compile the wiki
1. Go to the **Maintain** tab
2. Click **Compile** (first time) or **Ingest** (after adding new files)
3. Wait 30–90 seconds. The wiki pages appear automatically.

### Browse the wiki
Go to the **Browse Wiki** tab. Click any page to read it.

### Ask questions
Go to the **Ask** tab. Type a question like:
- "Why did we choose Postgres over MongoDB?"
- "What should a new engineer set up in their first week?"
- "What are the open questions on Project Alpha?"

### Weekly maintenance
Once a week, someone clicks **Lint** in the Maintain tab to check for inconsistencies and stale content.

---

## Deploying to Your Work Machine

```bash
# On your work machine
git clone <your-repo-url> llm-wiki
cd llm-wiki
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with API key
python server.py
```

To make it accessible to the team on your local network:

```bash
# server.py already binds to 0.0.0.0
# Team members can access it at http://<your-machine-ip>:5001
```

---

## Project Structure

```
llm-wiki/
├── server.py              ← Web server (run this)
├── web/index.html         ← Web UI
├── trim_jira.py           ← Jira CSV column trimmer
├── requirements.txt
├── .env                   ← API key (never commit)
├── .env.example
├── .gitignore
├── CLAUDE.md              ← Project context for Claude Code
├── _prompts/              ← Prompt templates for LLM operations
│   ├── compile_full.md
│   ├── ingest.md
│   └── lint.md
├── docs/                  ← Setup guides and documentation
│   ├── deployment.md
│   └── obsidian-setup.md
├── raw/                   ← Source files (upload here)
└── wiki/                  ← Generated wiki (LLM maintains this)
    ├── _schema.md         ← Rules for the LLM
    ├── _aliases.json      ← Name deduplication
    ├── _nav.md            ← LLM-generated navigation
    ├── _summary.md        ← Auto-generated status dashboard
    ├── _index.md          ← Page catalog
    └── _log.md            ← Operation log
```

The LLM decides the wiki page structure based on your content — there are no hardcoded categories.

---

## Optional: View in Obsidian

For a richer browsing experience with graph view and backlinks:

1. Download [Obsidian](https://obsidian.md)
2. Open vault → select the `wiki/` folder inside `llm-wiki`
3. Browse `wiki/` pages with full link navigation

This is completely optional — the web UI works standalone.
