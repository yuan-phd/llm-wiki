# Team Wiki

An LLM-powered knowledge base that compiles your team's scattered documents into a structured, searchable wiki. Based on [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern.

Everyone interacts through a web UI — no command line needed for daily use.

---

## Setup (One-time, on your build machine)

### 1. Clone and install

```bash
git clone <your-repo-url> team-wiki
cd team-wiki
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
git clone <your-repo-url> team-wiki
cd team-wiki
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
team-wiki/
├── server.py              ← Web server (run this)
├── web/index.html         ← Web UI
├── requirements.txt
├── .env                   ← API key (never commit)
├── .env.example
├── .gitignore
├── _prompts/              ← Prompt templates for LLM operations
│   ├── compile_full.md
│   ├── ingest.md
│   └── lint.md
├── raw/                   ← Source files (team uploads here)
│   ├── docs/
│   ├── slack/
│   ├── meetings/
│   └── code/
└── wiki/                  ← Generated wiki (LLM maintains this)
    ├── _schema.md
    ├── _index.md
    ├── onboarding/
    ├── projects/
    ├── decisions/
    ├── people/
    ├── faq/
    └── concepts/
```

---

## Optional: View in Obsidian

For a richer browsing experience with graph view and backlinks:

1. Download [Obsidian](https://obsidian.md)
2. Open vault → select the `team-wiki/` folder
3. Browse `wiki/` pages with full link navigation

This is completely optional — the web UI works standalone.
