# Files around llms.txt

Only `llms.txt` and the per-page Markdown convention are described by the proposal. Everything else here is practice that grew around it. Say which is which when you recommend something.

## Several llms.txt files (in the proposal)

The file may live at the root or at any sub-path, covers the URLs under its path, and the most specific file wins:

```text
https://example.com/llms.txt          covers the whole site
https://example.com/docs/llms.txt     covers /docs/** and is more specific there
https://example.com/docs/v2/llms.txt  covers /docs/v2/**
```

Use sub-path files when:
- several products share one domain — one file per product keeps each focused
- docs are versioned — one file per version, listing only that version's pages
- you can publish under one path but not at the root

Do not use them for a single product with a single version: one root file is simpler to keep correct.

Make the hierarchy discoverable by linking downward from the parent:

```markdown
## Areas

- [API docs index](https://example.com/docs/api/llms.txt): Endpoints, auth and SDKs
- [v2 docs index](https://example.com/docs/v2/llms.txt): Everything specific to version 2
```

Each file is validated on its own. Check sub-path files by their full address; tools that "discover" a site's llms.txt usually only try the root.

For versions: mark frozen versions as such in the entry description, and remove end-of-life versions from the parent index.

## Per-page Markdown (in the proposal)

The proposal suggests giving pages a clean Markdown twin so a reader does not have to strip HTML:

- `page.html` → `page.html.md` or `page.md` — pick one scheme for the whole site
- a URL without a file name (`/docs/guide/`) → `index.html.md` or `index.md`

and announcing it with link relations, as HTML elements or as an HTTP `Link` header:

```html
<link rel="alternate" type="text/markdown" href="/docs/guide.md" />
<link rel="describedby" type="text/plain" href="/docs/llms.txt" />
```

Practical notes:
- Generate the Markdown from the page's source (the CMS body, the `.md`/`.mdx` file), not by converting rendered HTML when the source is available.
- Strip navigation, footers and cookie banners. Keep code blocks, tables and headings.
- Serve it as `text/markdown; charset=utf-8`.
- Point llms.txt entries at the `.md` URL once those exist.

## llms-full.txt (not in the proposal)

A community convention: one file containing the full text of the pages the index links to.

- Fits small documentation sets a reader can take in one request.
- Costs: it grows without bound, it is a second artifact to keep in sync, and a reader that truncates decides what gets dropped, not you.
- It is not an index. Do not validate it with the index rules — it will have many headings and few links, and that is expected.

Recommend it only when the docs are small or the user knows a consumer that wants it. A good index plus per-page Markdown covers most needs.

Do not confuse it with `llms-ctx.txt` / `llms-ctx-full.txt`: those are outputs of the `llms_txt2ctx` tool, generated from an llms.txt by fetching its links. They are built, not written by hand.

## robots.txt and sitemap.xml

Three files, three questions:

| File | Answers | Not for |
| --- | --- | --- |
| `robots.txt` | What may automated clients fetch? | Describing content |
| `sitemap.xml` | Which pages exist for search engines to index? | Curation, summaries, external links |
| `llms.txt` | What should a model read to understand this site? | Granting or denying access |

Consequences worth stating to a user:
- An llms.txt does not override `robots.txt`. If a path is disallowed there, linking it in llms.txt is a contradiction — resolve it.
- Whether AI crawlers may train on or fetch the site is a `robots.txt` decision (and a business one). It is independent of having an llms.txt.
- Do not generate llms.txt by dumping the sitemap.

## Content negotiation for Markdown (outside the proposal)

Some hosts and CDNs can answer `Accept: text/markdown` with a Markdown rendering of an HTML page. It is an optional enhancement on top of everything above, not a substitute for an index: a reader still needs to know which pages to ask for. If the user's host offers it, turning it on is cheap; if not, per-page `.md` files achieve the same result.
