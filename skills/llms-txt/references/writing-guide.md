# Writing a useful llms.txt

Everything here is advice. None of it is required by the proposal (see `spec.md`). The goal is a file that lets a reader with a limited context window find the right page with the fewest wasted tokens.

## Choose what goes in

Think "what would I hand a new teammate on day one", not "every URL we have".

Include:
- how to get started (install, first request, first deploy)
- concept and architecture pages a reader needs before the reference makes sense
- reference pages people look things up in (API, configuration, CLI)
- migration and troubleshooting pages

Leave out:
- marketing, pricing tiers, press, careers, legal
- login-walled pages a reader cannot fetch
- auto-generated listings with no content of their own (tag pages, archives)
- near-duplicates — the same page per locale or per old version (give those their own file; see `related-files.md`)

A sitemap answers "what exists". An llms.txt answers "what should I read". If the list was produced by walking the sitemap, it is probably too long.

## Order

1. Put the sections a reader needs first at the top. Readers that truncate keep the beginning.
2. Inside a section, most-used page first.
3. `## Optional` last, holding what can be dropped under pressure: changelog, examples gallery, community links, old versions.

Section names are free. Use ones a reader can route on — `Docs`, `API`, `Guides`, `Examples`, `Reference` — rather than internal team names.

## The summary

One or two sentences. Cover:
- what the thing is, in plain words
- who it is for
- the single fact a model is most likely to get wrong (current major version, a renamed product, a deprecated API)

| Weak | Better |
| --- | --- |
| "Welcome to the Acme documentation." | "Acme is a hosted job queue with SDKs for Node, Python and Go. These docs cover API v2; v1 was shut down in 2025." |
| "The best platform for modern teams." | "CLI and API for deploying static sites from a Git repository." |

If nothing specific can be said, leave the summary out. An absent summary is allowed; an empty `>` line is a finding.

## The free-text part

Between the summary and the first H2 you may add paragraphs or lists — **no headings**. Use it for things that apply to the whole site and would otherwise be repeated: naming conventions, which version the docs describe, how sample code is licensed, where the Markdown versions of pages live. This is also where non-link notes belong; inside a section, every list item should be a link.

## Entries

```markdown
- [Page title](https://example.com/docs/page.md): What the reader gets from this page
```

- **Title**: the page's real title, so a reader can match it to the page it fetches.
- **URL**: absolute, `https://`, pointing at the canonical address. Link the Markdown version when one exists.
- **Description**: one clause that tells this page apart from its neighbours.

| Weak | Better |
| --- | --- |
| `- [Authentication](…): Authentication docs` | `- [Authentication](…): API keys, OAuth flow, token lifetimes and rotation` |
| `- [Guide](…): A helpful guide` | `- [Deploying to Kubernetes](…): Helm chart values, health probes and rolling updates` |
| `- [Errors](…)` | `- [Errors](…): Every error code with cause and remedy` |

Do not repeat the title as the description. If you cannot say what a page adds, question whether it belongs in the list.

## Size

There is no limit in the proposal. There is a limit in every reader. Work from the reader's side:

- An index of a few dozen entries is typically a few kilobytes — a small part of any context window.
- When the file grows past roughly a hundred entries, split by area or version into sub-path files and link to them from the root file.
- If the file is hundreds of kilobytes, page content has been pasted into it. That is a different artifact (`llms-full.txt`); keep the index an index.
- To trim: move to `## Optional` first, shorten descriptions second, remove links last.

## Honesty rules

- Only list pages that exist. Verify each URL you add; if you could not, say which ones.
- Do not write descriptions from the URL alone. Read the page, or mark the description as a guess for the user to confirm.
- Do not add sections to make the file look complete.
- Keep the file in the same change as the docs it points at. A link that died last month is worse than a missing one.

## Maintenance

After every docs release:
1. Structure still valid — run the validator.
2. Added, removed and renamed pages reflected in the entries.
3. Links still resolve — `--check-links` on the deployed file.
4. Size still reasonable.
5. Sub-path and version files still point at each other correctly.

Wire the first three into CI where possible: the validator exits non-zero on a spec failure or a dead link.
