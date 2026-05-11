# Using Obsidian with Team Wiki

Obsidian is an optional way to browse the wiki with graph view, backlinks, and fast search.

## Setup (2 minutes)

1. Download Obsidian from https://obsidian.md
2. Open Obsidian → "Open folder as vault"
3. Select the `wiki/` folder inside your team-wiki directory
4. Done. All pages, links, and graph view work immediately.

## What you get

- **Graph view**: see how all wiki pages connect to each other. Open from the left sidebar.
- **Backlinks**: open any page, the right panel shows every other page that links to it.
- **Search**: Cmd/Ctrl+Shift+F searches across all wiki pages instantly.
- **Quick switcher**: Cmd/Ctrl+O to jump to any page by name.

## Important

- Obsidian is read-only for the wiki. Do not edit wiki pages in Obsidian — the LLM maintains them.
- The web UI (localhost:5001) is still the primary tool for uploading files, asking questions, managing people, and running Compile/Ingest.
- Obsidian sees the same files. When you run Compile or Ingest in the web UI, refresh Obsidian to see updates.

## For the team

If the wiki is in a Git repo, team members can:
1. Clone the repo
2. Open the wiki/ folder in Obsidian
3. Pull regularly to stay updated
