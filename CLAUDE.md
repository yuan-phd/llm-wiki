# Team Wiki

LLM-powered team knowledge base. Based on Karpathy's LLM Wiki pattern.

## Project Structure
- server.py — Flask web server, all backend logic
- web/index.html — Single-page frontend
- _prompts/compile_full.md — Prompt for full wiki compilation
- _prompts/ingest.md — Prompt for incremental wiki updates
- _prompts/lint.md — Prompt for wiki health checks
- wiki/ — LLM-generated wiki pages (markdown)
- wiki/_schema.md — Rules for the LLM
- wiki/_aliases.json — Name deduplication overrides
- wiki/_summary.md — Auto-generated project summary
- wiki/_nav.md — Auto-generated navigation structure
- wiki/_log.md — Append-only operation log
- wiki/_index.md — Page catalog
- raw/ — Raw source files (immutable, LLM reads but never modifies)

## Tech Stack
- Python 3 + Flask
- OpenAI API (gpt-5.1 for compile/ingest/lint, gpt-5-mini for ask/summary/nav)
- Single HTML file with vanilla JS, no framework

## Key Rules
- Files starting with _ in wiki/ are system files, never deleted during compile
- Compile deletes all non-_ wiki files before rebuilding
- Ingest is incremental — adds to existing wiki
- All wiki links use [[path/filename|Display Name]] format
- max_completion_tokens = 32768
- MAX_TOKENS_PER_BATCH = 25000

## Editing Guidelines
When editing server.py or index.html, only change what is asked. Do not refactor or reorganize other parts.