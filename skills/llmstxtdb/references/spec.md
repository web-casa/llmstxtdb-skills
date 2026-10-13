# What the llmstxt.org proposal says

Source: the proposal text at <https://llmstxt.org>, as read in August 2026. It is a proposal, not a ratified standard; it has changed before and may change again. When a user needs certainty, read the live page.

## Location

- The file is named `llms.txt`. It lives at the root path `/llms.txt` **or at any sub-path** (for example `/docs/llms.txt`).
- A file covers the URLs under its path. Where more than one file applies, an agent should use the most specific one.

## Contents, in this order

1. An optional byte-order mark.
2. **An H1 with the name of the project or site. This is the only required section.**
3. A blockquote with a short summary, carrying the key information needed to understand the rest of the file.
4. Zero or more Markdown sections (paragraphs, lists and so on) **of any type except headings**, with more detail about the project and how to read the linked files.
5. Zero or more sections delimited by **H2** headings, each containing a "file list" of URLs where more detail is available.

Each file list is a Markdown list. Each item has a **required Markdown hyperlink** `[name](url)`, then optionally a `:` and notes about the file.

A section named **`Optional`** is used, by convention, for secondary information: links an agent can skip when a shorter context is needed.

## Companion suggestions in the proposal

- Pages worth reading should have a clean Markdown version at the same URL with `.md` appended (`page.html.md`) or with the extension replaced (`page.md`). URLs without a file name use `index.html.md` or `index.md`.
- Link relations help clients find these: `rel="alternate" type="text/markdown"` points to the Markdown version of a page; `rel="describedby"` points to the llms.txt that covers it.
- llms.txt is meant to coexist with `robots.txt` (what access is acceptable) and `sitemap.xml` (what pages exist for search engines). It replaces neither.

## How the rules map to findings

| Proposal text | Finding when violated | Level |
| --- | --- | --- |
| an H1 … the only required section | `SPEC_H1_MISSING` | fails |
| *an* H1 (one project name) | `SPEC_H1_MULTIPLE` | fails |
| a blockquote with a short summary | `SPEC_SUMMARY_EMPTY` when the blockquote is present but empty. A missing summary is **not** a spec finding. | warns |
| sections delimited by H2 | `SPEC_SECTION_DEPTH` when H3 or deeper is used | warns |
| a required Markdown hyperlink | `SPEC_ENTRY_NOT_LINK`, once per list item without a link | warns |

A file with only warnings still satisfies the one hard requirement. Say so plainly instead of calling it "invalid".

## Not in the proposal

These show up in other tools and guides as if they were rules. They are not:

| Claim | Reality |
| --- | --- |
| "At least N sections are required" | Zero sections is allowed. |
| "Every entry needs a description" | The `: notes` part is optional. |
| "URLs must be absolute" | Not stated. Relative URLs depend on the reader resolving them against the file's address, so absolute is safer — that is advice. |
| "The file must be under N kilobytes" | No limit is stated. Size matters for the reader's context budget, which is a practical concern. |
| "`llms-full.txt` is part of the standard" | The proposal does not define it. It is a community and vendor convention. |
| "llms.txt controls what crawlers may fetch" | It carries no permission semantics. That is `robots.txt`. |
| "Having an llms.txt improves ranking or gets a site cited" | The proposal claims nothing of the kind, and neither should you. |

Findings about these topics belong under *advice* (`ADVICE_*`) or *usability*, never under *spec*.

## Differences from the online checker

The bundled validator is a line-based reader written with the Python standard library. The llmstxtdb web checker parses a full Markdown syntax tree. Both apply the same rules, and they agree on every file in `scripts/fixtures/strict/` — that is enforced by tests on both sides, with per-code counts, not just "same set of codes".

They can differ on Markdown that leans on fine print of the CommonMark specification. The known cases are pinned in `scripts/fixtures/divergent/`, each with the result of both sides:

| Fixture | What is unusual | Effect |
| --- | --- | --- |
| `tab-text-then-ordered.txt` | A tab-indented line directly under an empty block-quote line, followed by an ordered list that does not start at 1 | The validator reads the list as plain text and misses a non-link item. |
| `quote-then-indented-item.txt` | A list item indented four or more columns directly under a block-quote line, with no blank line between | The validator misses a non-link item. |
| `indented-item-after-code.txt` | An indented code block, a list that does not start at 1, a thematic break and indented continuation text in sequence | The validator reports one non-link item more than the checker. |
| `definition-under-code.txt` | A link reference definition on the line directly after an indented code block, later used by a list item | The validator does not resolve the reference and reports the item as a non-link. |

All four involve **indented code or block quotes touching the next block without a blank line**. Normal llms.txt files do not look like this. In a random comparison over ten thousand deliberately malformed documents, the two disagreed on about 0.2 percent.

Practical rule: if the validator and the online checker disagree, put blank lines between blocks and re-run. If they still disagree, trust the online checker for a deployed file.
