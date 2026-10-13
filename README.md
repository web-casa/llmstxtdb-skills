# llmstxtdb skills

[![Validate](https://github.com/web-casa/llmstxtdb-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/web-casa/llmstxtdb-skills/actions/workflows/validate.yml)

An open Agent Skill for writing, checking, fixing and deploying [`llms.txt`](https://llmstxt.org) files — the Markdown index that gives a language model a short, curated way into a site's documentation.

It comes from **llmstxtdb**, a directory of llms.txt files that checks each one for reachability, structure and link health. The skill packages the same rules and the same issue codes for use inside a coding agent.

[中文说明](README.zh-CN.md)

## What it does

- **Write** an llms.txt for a project or site: what to include, how to order it, how to describe each link.
- **Validate** a local file or a deployed URL with a bundled, dependency-free script.
- **Fix** findings by code (`SPEC_H1_MISSING`, `SPEC_ENTRY_NOT_LINK`, `SPA_DETECTED`, `LINK_HEALTH`, …), with the reason each check exists and how to confirm the fix.
- **Debug a deployment** where `/llms.txt` returns 404, an HTML page, the wrong content type or a redirect chain.
- **Advise** on sub-path files, per-page Markdown versions and `llms-full.txt`.

## What makes it different

- **It keeps three things apart.** What the proposal *requires* (one H1 and little else), what makes a file *usable in practice* (it must be served and its links must work), and what is merely *good writing*. Many guides present their own preferences as "the spec".
- **Same codes as the online checker.** A finding from the local validator and one from an llmstxtdb report mean the same thing. Shared fixtures are tested on both sides, down to per-code counts.
- **It does not overpromise.** An llms.txt does not make any AI product read, cite or rank a site, and the skill tells the agent not to say so.
- **The validator is careful with the network.** http(s) only, no credentials in URLs, private addresses refused unless you opt in, redirects re-checked hop by hop, a 2 MB read cap, and a hard deadline enforced by running each request in a child process.

## Install

With the `skills` CLI (works for Claude Code, Codex and other agents that load Agent Skills):

```bash
npx skills add https://github.com/web-casa/llmstxtdb-skills --list          # inspect first
npx skills add https://github.com/web-casa/llmstxtdb-skills --skill llmstxtdb
```

As a Claude Code plugin:

```text
/plugin marketplace add web-casa/llmstxtdb-skills
/plugin install llmstxtdb@llmstxtdb-skills
```

By hand: copy the whole `skills/llmstxtdb/` directory into your agent's skills directory (for Claude Code, `~/.claude/skills/` or `.claude/skills/` in a project). Copy the directory, not `SKILL.md` alone — the references and the validator are part of the skill.

**Upgrading from 0.1.0.** The skill was renamed from `llms-txt` to `llmstxtdb` in 0.2.0, so that it is not confused with other skills about llms.txt. Remove the old `llms-txt` directory from your agent's skills directory (or run `npx skills remove llms-txt`) before installing, otherwise the agent will find two copies. Invoke it as `/llmstxtdb`; installed as a Claude Code plugin it is `/llmstxtdb:llmstxtdb`.

## Use

Ask in plain words:

- "Create an llms.txt for this docs site."
- "Check `public/llms.txt`."
- "My report shows 65 × SPEC_ENTRY_NOT_LINK — fix them."
- "`https://example.com/llms.txt` returns HTML. Why?"

Or run the validator yourself (Python 3.9+, standard library only):

```bash
python3 skills/llmstxtdb/scripts/validate_llms_txt.py public/llms.txt
python3 skills/llmstxtdb/scripts/validate_llms_txt.py https://example.com/llms.txt --check-links
python3 skills/llmstxtdb/scripts/validate_llms_txt.py public/llms.txt --json
```

```text
llms.txt check: public/llms.txt

Spec (llmstxt.org proposal): WARN
  [MINOR] SPEC_ENTRY_NOT_LINK x3 - List item has no link (entry format is `- [name](url): description`); 3 such item(s) in the file. | line 14, 15, 16

Advice (editorial, not part of the proposal): 1
  ADVICE_ENTRY_NO_DESCRIPTION - 2 entries without a description. | first at line 9

Metrics: 812 bytes, 2 section(s), 7 entries
```

Exit status is `1` on a spec failure or a failed deployment check, so it drops into CI:

```yaml
- run: python3 skills/llmstxtdb/scripts/validate_llms_txt.py public/llms.txt
```

## What is in the box

```text
skills/llmstxtdb/
├── SKILL.md                     the workflow the agent follows
├── references/
│   ├── spec.md                  what the proposal says, what it does not, known validator differences
│   ├── error-codes.md           every issue code: meaning, why, effect, fix, confirmation
│   ├── error-codes.zh-CN.md     the same in Chinese, generated from the checker's fix handbook
│   ├── writing-guide.md         selecting, ordering and describing entries
│   ├── deployment.md            where each stack serves the file from; the SPA fallback trap
│   └── related-files.md         sub-path files, per-page Markdown, llms-full.txt, robots and sitemap
└── scripts/
    ├── validate_llms_txt.py     the validator
    ├── test_validate.py         its tests (no external network)
    └── fixtures/                shared with the online checker's test suite
```

## Local validator and online checker

The validator covers the loop while you write: structure, advice and a look at one deployed URL. The llmstxtdb web checker covers what needs a service: link health across a whole file, change tracking over time, and a letter grade with a score. The validator deliberately outputs no grade — grading is defined by the online checker's published rules.

The two parse Markdown differently (line-based here, a full syntax tree there). They agree on all fixtures in `scripts/fixtures/strict/`; the handful of unusual constructs where they differ are pinned in `scripts/fixtures/divergent/` and explained in `references/spec.md`.

## Develop

```bash
python3 skills/llmstxtdb/scripts/test_validate.py
```

The fixtures' expected results come from the llmstxtdb engine. Changes to parsing rules are made there first; this repository is exported from it.

## Acknowledgements

Written from scratch, with ideas about how to organise such a skill taken from these MIT-licensed projects (no text or code was copied):

- [johnericforte/claude-skill-llms-txt](https://github.com/johnericforte/claude-skill-llms-txt) (at `3f7f4f0`) — a dependency-free validator with good/bad fixtures; keeping non-document links out of file lists.
- [cartoonitunes/inlay-skills](https://github.com/cartoonitunes/inlay-skills) (at `c73a176`) — the analyse → generate → place → verify outline; a per-framework placement table.
- [microsoft/skills](https://github.com/microsoft/skills) `wiki-llms-txt` (at `d5741a1`) — weak/strong description pairs; a pre-delivery checklist.

The format itself is the [llmstxt.org](https://llmstxt.org) proposal by Jeremy Howard.

## License

[MIT](LICENSE)
