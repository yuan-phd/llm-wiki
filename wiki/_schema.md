# Wiki Schema

## Link Format (MANDATORY)

ALL internal links must use `[[path/filename|Display Name]]` format.

NEVER use `__filename.md__` or bare filenames. ONLY `[[path/filename|Display Name]]` links.

## Frontmatter (MANDATORY)

Every page must have YAML frontmatter with at minimum:

```yaml
---
title: Display Title
last_updated: YYYY-MM-DD
sources:
  - raw/some-file.txt
---
```

## Name Rules

- Preserve non-ASCII characters in display names (e.g. umlauts, accents).
- Filenames use ASCII only: ö → oe, ü → ue, ä → ae, é → e, etc.
- One page per real person. List all name variants on the person's page.
- Read `wiki/_aliases.json` for explicit name overrides. Always follow those.

## Project Definition

A project is a business initiative, not a code repository. Backend and frontend repos that serve the same product are ONE project. Example: `[your-project]-be` and `[your-project]-fe` are components of the same "[Your Project]" project — they belong on a single project page, not two.

## Page Structure

Page structure is determined by the LLM based on content. The only requirements are: YAML frontmatter, `[[wikilinks]]`, and clear markdown formatting.

The LLM decides how to organize pages. It may create folders or keep pages flat. Structure emerges from content, not from a prescribed template. Do NOT assume specific folder categories like `people/`, `projects/`, or `decisions/`.
