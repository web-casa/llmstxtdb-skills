---
name: llmstxtdb
description: Write, review, fix and deploy llms.txt files that follow the llmstxt.org proposal. Use when the user asks to create or generate an llms.txt, audit or validate an existing one, fix issues from an llmstxtdb report (codes such as SPEC_H1_MISSING, SPEC_ENTRY_NOT_LINK, SPA_DETECTED, LINK_HEALTH), or debug why a deployed /llms.txt is not readable (404, HTML returned instead of Markdown, wrong Content-Type, redirects). Also covers llms-full.txt, per-page .md versions and sub-path llms.txt files. Triggers - llms.txt, llms-full.txt, llmstxt, "make my docs readable by AI agents", "LLM-friendly docs index", 生成 llms.txt, 检查 llms.txt, 修复 llms.txt. Not for robots.txt or sitemap.xml work.
license: MIT
metadata:
  author: llmstxtdb
  version: "0.2.0"
---

# llms.txt

`/llms.txt` is a Markdown file that gives a language model a short, curated way into a site's documentation: one project name, one summary, and grouped links to the pages worth reading. It is a **proposal** (llmstxt.org), not a ratified standard.

Hold on to three distinctions. Most bad advice about llms.txt comes from blurring them.

1. **What the proposal requires** — very little: one H1. Everything else is optional but has a defined shape.
2. **What makes the file usable in practice** — it must actually be served as text at its URL, and its links must work. None of this is in the proposal.
3. **What is merely good writing** — a summary, descriptions, sensible grouping. Useful, never mandatory.

Report findings in those three groups and never present group 2 or 3 as "the spec says".

**What this skill does not promise.** An llms.txt does not make any AI product read, cite or rank a site. Do not tell the user it will. The deliverable is a file that is correct, reachable and cheap to read.

## Pick the task

| The user wants… | Go to |
| --- | --- |
| a new llms.txt for a project or site | [Write](#write-a-new-file) |
| an existing file checked | [Validate](#validate) |
| findings from a report fixed | [Fix by code](#fix-by-code) |
| to know why the deployed file "doesn't work" | [Deployment check](#deployment-check) |
| llms-full.txt, per-page `.md`, several llms.txt files | `references/related-files.md` |

## The format, exactly

```markdown
# Project Name

> One or two sentences: what this is and who it is for.

Optional free text: constraints, version notes, things a reader would get wrong without being told.

## Docs

- [Getting started](https://example.com/docs/start.md): Install and first request
- [API reference](https://example.com/docs/api.md): Endpoints, auth, errors

## Optional

- [Changelog](https://example.com/changelog.md): Release history
```

- **H1** — exactly one, the project or site name. The only required element.
- **Blockquote summary** — optional. If the `>` is there it must not be empty.
- **Free text** — optional paragraphs and lists, before the first H2. No headings here.
- **H2 sections** — optional, any number, any names. Each holds a list of entries. Use H2 only; deeper headings have no defined meaning.
- **Entry** — `- [name](url)` optionally followed by `: description`. A list item with no link is not an entry.
- **`## Optional`** — by convention, links a reader may skip when context is tight. (Placing it last is sensible, but the proposal does not require a position.)

Things often claimed as requirements that are **not** in the proposal: a minimum number of sections, a description on every entry, absolute URLs, a size limit, `llms-full.txt`. Detail and sources: `references/spec.md`.

## Write a new file

1. **Find the sources.** Look for a docs directory, the site's navigation or sidebar config, the sitemap, the README. Prefer pages that have (or can have) a Markdown version. If the site is not in the workspace, ask for the docs URL rather than guessing page addresses.
2. **Decide the scope.** One product and one version per file. For a large site, a root file that links to per-area files beats one enormous list (`references/related-files.md`).
3. **Select, do not dump.** An index, not a sitemap: the pages a newcomer needs first, then reference material, then the rest under `## Optional`. Leave out marketing, legal and login pages.
4. **Write the summary last**, once you know what the file contains: what the thing is, who uses it, and the one fact a model would otherwise get wrong.
5. **Write each entry as** `- [Page title](absolute URL): what the reader will find there`. The description should distinguish this page from its neighbours — "Auth" tells nothing; "API keys, OAuth flow and token lifetimes" does.
6. **Only link pages you have confirmed exist.** Never invent URLs to make the list look complete. If you could not verify a link, say so.
7. Validate (below), then place the file where the stack serves static files from (`references/deployment.md`).

More on selection, ordering, descriptions and size: `references/writing-guide.md`.

## Validate

Run the bundled validator. Python 3.9+, standard library only.

```bash
python3 scripts/validate_llms_txt.py path/to/llms.txt
python3 scripts/validate_llms_txt.py https://example.com/llms.txt            # also observes the deployment
python3 scripts/validate_llms_txt.py https://example.com/llms.txt --check-links
python3 scripts/validate_llms_txt.py path/to/llms.txt --json                 # for further processing
```

(`scripts/` is relative to this skill's directory.)

Output has three parts that mirror the three distinctions:

- **Spec** — `PASS`, `WARN` or `FAIL` against the proposal. `FAIL` means a missing or duplicated H1.
- **Usability** — only for a URL: status, content type, whether an HTML page came back instead of the file, size. With `--check-links`, a sample of entry links.
- **Advice** — editorial suggestions, each marked non-standard. They never change the spec verdict.

Exit status is `1` when spec or usability is `FAIL`, otherwise `0`.

Network behaviour, so you can tell the user what a URL check does: it fetches only `http(s)`, refuses URLs with credentials, refuses hosts that resolve to private or loopback addresses unless `--allow-private` is given, follows at most five redirects re-checking each hop, reads at most 2 MB, and stops every request at a hard deadline. Link checking is off unless asked for and samples at most twenty links.

If Python is unavailable, check by hand against `references/spec.md`: count the `# ` lines outside code blocks, look for an empty `>` line, look for `###`, and look for list items with no `[text](url)`.

## Fix by code

The validator and the llmstxtdb web checker use the same issue codes. `references/error-codes.md` has every code with what it means, why it is checked, what it does to a reader, the fix and how to confirm it. The frequent ones:

| Code | Fix |
| --- | --- |
| `SPEC_H1_MISSING` | Make the first line `# Project name`. |
| `SPEC_H1_MULTIPLE` | Keep one `# ` line; turn the others into `## ` sections or plain text. |
| `SPEC_SUMMARY_EMPTY` | Fill the `>` line with a real sentence, or delete it. |
| `SPEC_SECTION_DEPTH` | Promote `###` and deeper to `##`, or fold them into entry descriptions. |
| `SPEC_ENTRY_NOT_LINK` | Turn the item into `- [name](url): description`. If it was never meant to be a link, move it out of the list into a paragraph above the first H2. |
| `SPA_DETECTED` | The server answered `/llms.txt` with the app's HTML shell. Exclude the path from the SPA fallback or put the file where static files are served. |
| `CONTENT_TYPE` | Serve as `text/plain` or `text/markdown`. |
| `LINK_HEALTH` | Update or remove dead links. Timeouts and refusals mean "not confirmed", not "dead" — re-check before deleting. |

Rules for fixing:

- **Work on the real file.** If you only have findings and not the file, ask for it. Do not reconstruct content from a report.
- **Smallest change that clears the finding.** Do not reorder or rewrite entries that were not flagged.
- **Many identical findings usually have one cause.** Forty `SPEC_ENTRY_NOT_LINK` items are normally one section written as prose bullets: decide once whether that section should be links or text.
- **Re-run the validator** and report what changed, with before and after counts.

## Deployment check

When the file exists locally but tools "can't read it", look at what the server really returns:

```bash
curl -sS -D - -o /dev/null https://example.com/llms.txt      # status, Content-Type, redirects
curl -sS https://example.com/llms.txt | head -n 5            # should start with "# ", not "<!doctype html>"
```

Read the result in this order — each step only makes sense if the previous one passed:

1. **Status 200?** If a redirect ends in 404, look at the final URL: the path may be wrong, the file may not be deployed there, or a routing rule may be answering.
2. **Is the body Markdown?** `<!doctype html>` or `<div id="root">` means a single-page-app fallback is answering for every unknown path.
3. **Content-Type** `text/plain` or `text/markdown`.
4. **Redirects** — one hop at most (`http`→`https`, or apex→`www`), not a chain.
5. **Size** — an index is normally a few kilobytes. Hundreds of kilobytes means page bodies were pasted in.

Where each stack serves static files from, how to keep an SPA fallback away from `/llms.txt`, and server snippets: `references/deployment.md`.

## Before you hand it over

- [ ] Exactly one H1, and it is the project name
- [ ] The summary says something specific to this project, or is absent — not empty, not boilerplate
- [ ] Sections are H2; nothing deeper
- [ ] Every list item under a section is a link
- [ ] Every link was confirmed to exist; no invented URLs
- [ ] Absolute `https://` URLs (advice, not a rule — relative ones depend on the reader resolving them)
- [ ] Most important sections first; `## Optional` last (advice — the proposal fixes no position)
- [ ] The validator reports no `FAIL`
- [ ] If deployed: 200, text content type, body starts with `# `
- [ ] The user has been told what was verified and what was not

## Checking a live site online

The llmstxtdb web checker runs the same structural rules against a deployed file and adds what a local run cannot see: link health across the whole file, change tracking over time, and a letter grade. Use it to confirm a deployment. This skill's validator is for the local loop — while writing, in CI, before publishing.

The two can disagree on a handful of unusual Markdown constructs; those are listed at the end of `references/spec.md`. For a deployed file, the online result is the one to trust.
