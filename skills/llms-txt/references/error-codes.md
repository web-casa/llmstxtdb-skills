# Issue codes

The same codes are used by the bundled validator and by the llmstxtdb web checker, so a local run and an online report can be read side by side. A Chinese version generated from the checker's own fix handbook is in `error-codes.zh-CN.md`.

Each code has: what it **means**, **why it is checked**, the **effect on readers**, the **fix**, and how to **confirm** the fix.

Two conventions to keep when explaining a finding to a user:

- Describe what *this check* observed. A timeout or a refusal seen by one client does not establish what every other reader will see.
- Keep the three groups apart: *structure* is the proposal; *usability* and *fetching* are observations about a deployment; *advice* is editorial.

## Structure — the proposal

These come from the llmstxt.org proposal. The local validator reports all of them.

### SPEC_H1_MISSING

*Level: fails*

- **Means:** No H1 title.
- **Why it is checked:** The H1 is the only element the proposal requires; it names the project the file belongs to.
- **Effect on readers:** The file carries no project name. A reader has to infer what it describes from the domain or the entries.
- **Fix:**
  1. Make the first line `# Project name` — one `#`, a space, plain text.
  2. Keep exactly one H1; start sections at `## `.
  3. If the file is really a full-text dump (`llms-full.txt`), check the index file at `/llms.txt` instead.
- **Confirm:** `grep -c '^# ' llms.txt` prints 1 and the finding is gone.

### SPEC_H1_MULTIPLE

*Level: fails*

- **Means:** More than one H1.
- **Why it is checked:** The proposal defines a single H1, which fixes the project name and where the document starts.
- **Effect on readers:** Parsers may disagree about which heading is the name and where the document begins.
- **Fix:**
  1. Keep the project name as the only `# ` line.
  2. Turn every other `# ` into `## ` (a section) or plain text.
  3. List them with `grep -n '^# ' llms.txt`.
- **Confirm:** `grep -c '^# ' llms.txt` prints 1.

### SPEC_SUMMARY_EMPTY

*Level: warns*

- **Means:** The summary blockquote exists but is empty.
- **Why it is checked:** The summary tells a reader what the project is before it reads any entry; a blockquote that is present should say something.
- **Effect on readers:** An empty quote adds nothing. The reader falls back on the title and the entries to work out what the site is.
- **Fix:**
  1. Write one or two sentences after `> `: what it is, who it is for.
  2. Or delete the empty `>` line — a missing summary is allowed.
- **Confirm:** The finding is gone; the summary appears in the validator's JSON output.

### SPEC_SECTION_DEPTH

*Level: warns*

- **Means:** Headings deeper than H2.
- **Why it is checked:** The proposal delimits sections with H2. Parsers look for H2 to find section boundaries.
- **Effect on readers:** H3 and deeper are not recognised as sections; entries under them may be attributed to the previous H2 or lose their grouping.
- **Fix:**
  1. Promote headings that group entries to `## `.
  2. Fold finer subdivisions into the entry descriptions.
- **Confirm:** No line starts with `###`; the finding is gone.

### SPEC_ENTRY_NOT_LINK

*Level: warns*

- **Means:** A list item contains no Markdown link. Reported once per item.
- **Why it is checked:** The proposal defines an entry as a Markdown hyperlink; readers follow the URL to fetch the page.
- **Effect on readers:** The line is not recognised as an entry. Tools that extract links get no address for it.
- **Fix:**
  1. Rewrite as `- [Title](https://full.url): optional description`.
  2. Use a full URL without angle brackets or backticks around it.
  3. If the line was never meant to be a link, move it into a paragraph above the first H2.
  4. Many of these at once usually means one section was written as prose bullets — fix the section, not each line.
- **Confirm:** The count drops to zero; `grep -n '^[-*+] ' llms.txt | grep -v ']('` shows nothing unexpected.

## Checker limit — structure not fully checked

Not a proposal rule and not a defect in the file. The code keeps its `SPEC_` name for compatibility with existing reports. Only the web checker emits it.

### SPEC_STRUCTURE_MISSING

*Level: fails*

- **Means:** Reported by the web checker when the response body was cut off because it exceeded the read limit, so the structure result rests on incomplete content.
- **Why it is checked:** It marks that the structure check could only cover the part that was read.
- **Effect on readers:** Only the first part of the file was examined. This does not show that the original file lacks structure.
- **Fix:**
  1. Reduce the file size: an index should be a few kilobytes.
  2. Move page bodies out of the index into linked pages or sub-path files.
  3. Check again.
- **Confirm:** The online report no longer carries a truncation notice.

## Usability — the deployed file

Observations about a URL. They are not proposal rules. The local validator reports the first four when given a URL; the web checker reports all of them.

### HTTP_STATUS

*Level: fails*

- **Means:** The request for the file did not return usable content (an error status or a network failure; the sub-code names the cause).
- **Why it is checked:** Everything else depends on getting the file.
- **Effect on readers:** This request got no content, so nothing further could be checked. Whether other readers can reach it depends on their network and the site's access rules.
- **Fix:**
  1. `curl -sS -D - -o /dev/null <url>` and read the status and `Location` headers.
  2. 404 after a redirect: look at the final URL. Possible causes are a wrong path, a file that was not deployed, a routing rule, or the file living on a different host than the redirect target — check the build output and the routing before changing anything.
  3. 401/403: make the path public; 5xx: fix the server or the route producing the file.
- **Confirm:** The same curl shows 200 and the body starts with `# `.

### CONTENT_TYPE

*Level: warns or fails*

- **Means:** The response type is not a text type (for example `text/html`).
- **Why it is checked:** The type tells a client how to treat the body.
- **Effect on readers:** When the declared type and the content disagree, some clients treat the file as a web page or do not parse it.
- **Fix:**
  1. Serve `.txt` as `text/plain; charset=utf-8` or `text/markdown; charset=utf-8`.
  2. If a route generates the file, set the header explicitly.
  3. If the type is HTML because an HTML page is being returned, see `SPA_DETECTED`.
- **Confirm:** `curl -sI <url> | grep -i content-type` shows a text type.

### SPA_DETECTED

*Level: fails*

- **Means:** The response looks like an HTML application shell rather than a Markdown file.
- **Why it is checked:** Single-page apps often answer every unknown path with their index page, so the URL returns 200 without serving the file.
- **Effect on readers:** If an app page is what really came back, a tool reading it as a document does not get the expected content. Confirm against the body.
- **Fix:**
  1. Check the file is in the deployed output.
  2. Exclude `/llms.txt` from the catch-all rewrite, or make static files take precedence (see `deployment.md`).
  3. Unknown paths should return 404, not the shell.
- **Confirm:** `curl -sS <url> | head -n 1` starts with `# `, not `<!doctype html>`.

### FILE_SIZE

*Level: warns*

- **Means:** The file is empty, or it was larger than the read limit and was cut off.
- **Why it is checked:** Records the size and flags the two cases where the content read is not the whole file.
- **Effect on readers:** An empty file has nothing to read. When the download was cut off, the unread part was not checked — that does not mean the original lacks it.
- **Fix:**
  1. Empty: publish the real file; check the build step that generates it.
  2. Too large: trim to an index; move content into linked pages.
- **Confirm:** Size is a few kilobytes and the warning is gone.

### SOFT_404

*Level: warns*

- **Means:** Status 200, but the body looks like an error page. A heuristic — confirm by eye.
- **Why it is checked:** Some servers answer 200 for missing pages, so the status alone does not prove the file exists.
- **Effect on readers:** If it really is an error page, readers get error text instead of the document.
- **Fix:**
  1. Open the URL and look at the body.
  2. Make missing paths return a real 404.
- **Confirm:** The body is the Markdown file.

### TOKEN_ESTIMATE

*Level: warns*

- **Means:** Token estimate for the content read; warns when the file is empty or was cut off.
- **Why it is checked:** Gives an idea of how much context the file occupies.
- **Effect on readers:** The estimate is not any model's real budget. For an empty file there is nothing; when cut off it covers only the part read.
- **Fix:**
  1. Treat it as a size signal: move secondary links under `## Optional`, shorten descriptions, split by area.
- **Confirm:** The estimate drops after trimming.

### LINK_HEALTH

*Level: warns or fails*

- **Means:** Some entry links are dead, or could not be confirmed.
- **Why it is checked:** Entries are the way into the documentation; this observes whether they resolve and separates dead from unconfirmed.
- **Effect on readers:** A confirmed-dead link gives no page. Timeouts, rate limits and refusals only show that this run could not get through — not that other readers cannot.
- **Fix:**
  1. Dead (404/410, domain does not resolve): update to the new address or remove the entry.
  2. Redirected: link the final address directly.
  3. Not confirmed (timeout, 403, 429): open it yourself before deleting anything; check whether a firewall is blocking automated clients.
- **Confirm:** Re-run with `--check-links`; dead count is zero.

### MARKDOWN_NEGOTIATION

*Level: informational*

- **Means:** Whether a sampled page answers `Accept: text/markdown` with Markdown. An optional capability, never a failure.
- **Why it is checked:** Observes a practice outside the proposal.
- **Effect on readers:** Optional enhancement, not a proposal rule. Only one entry is sampled; when Markdown is not returned a reader handles whatever type came back.
- **Fix:**
  1. Nothing to fix. To offer it, enable the host's Markdown-for-agents feature or publish per-page `.md` files.
- **Confirm:** `curl -H 'Accept: text/markdown' <page>` returns `text/markdown`.

## Fetching — network and safety

Reasons a request did not complete. On the web checker these appear as sub-codes of `HTTP_STATUS` or on individual links. Several describe the checker's own limits rather than a fault in the file.

### DNS_ERROR

*Level: fails*

- **Means:** The host name did not resolve.
- **Why it is checked:** Resolution is the first step of any request.
- **Effect on readers:** This request did not reach the target. A transient resolver error may clear on retry, and other readers may get a different result.
- **Fix:**
  1. Check the domain in the URL for typos.
  2. `dig +short <host>`; fix the DNS record if it is your domain.
- **Confirm:** The host resolves and the request completes.

### TLS_ERROR

*Level: fails*

- **Means:** Certificate or TLS handshake failure.
- **Why it is checked:** The checker stops on handshake errors and does not work around them.
- **Effect on readers:** The checker got no content. Whether other clients also fail depends on their certificate checks and protocol support.
- **Fix:**
  1. `curl -vI https://<host>/` to read the certificate error.
  2. Renew or reissue the certificate; include the full chain; make sure it covers this host name.
- **Confirm:** `curl -sI https://<host>/llms.txt` succeeds without `-k`.

### NETWORK_ERROR

*Level: fails*

- **Means:** Connection refused, reset, or broken while reading.
- **Why it is checked:** Records that the connection or read failed; the cause may be the server, the path, or an aborted check.
- **Effect on readers:** No content was obtained this time. Such failures are often temporary.
- **Fix:**
  1. Retry; if it persists, check the server and any firewall in front of it.
- **Confirm:** The request completes.

### TIMEOUT

*Level: fails*

- **Means:** The request, or the whole check, hit its time limit.
- **Why it is checked:** Requests and checks have a time limit so they cannot run forever.
- **Effect on readers:** Complete content was not obtained in time. This is not the same as a dead link, and other readers may not time out.
- **Fix:**
  1. Make sure the file is served statically rather than rendered per request.
  2. Check for slow middleware or bot challenges on the path.
- **Confirm:** The file returns in well under a second.

### TOO_LARGE

*Level: fails*

- **Means:** Reserved code for a body exceeding the single-file limit. Today this situation shows up as a truncation notice plus `FILE_SIZE` and `TOKEN_ESTIMATE` warnings.
- **Why it is checked:** Reading stops at the limit.
- **Effect on readers:** The part beyond the limit was not read; conclusions rest on the part that was.
- **Fix:**
  1. Trim the file to an index (see `FILE_SIZE`).
- **Confirm:** No truncation notice.

### TOO_MANY_REDIRECTS

*Level: fails*

- **Means:** The redirect chain is longer than the checker follows.
- **Why it is checked:** Clients only follow a limited number of redirects.
- **Effect on readers:** The request stops before reaching the file.
- **Fix:**
  1. `curl -sIL <url> | grep -i '^location'` to see the chain.
  2. Collapse it to a single redirect to the final address; link the final address.
- **Confirm:** One redirect or none.

### RATE_LIMITED_ORIGIN

*Level: not a finding*

- **Means:** The server asked the checker to slow down (429).
- **Why it is checked:** The checker honours the request and pauses.
- **Effect on readers:** The check could not complete; this does not indicate a problem with the file. If the same limit applies to other automated readers, they are turned away too.
- **Fix:**
  1. Check again later.
  2. If your own rate limiter did this, allow modest automated traffic on documentation paths.
- **Confirm:** The next check completes.

### BUDGET_EXCEEDED

*Level: not a finding*

- **Means:** The check used up its request allowance before finishing.
- **Why it is checked:** Each check has a fixed number of requests.
- **Effect on readers:** The check could not complete; this does not indicate a problem with the file. Links not reached are in an unknown state.
- **Fix:**
  1. Nothing to fix in the file. A very long link list is a reason to split it.
- **Confirm:** The report shows full coverage.

### SAFE_BLOCKED_SCHEME

*Level: blocked*

- **Means:** A URL that is not `http` or `https`.
- **Why it is checked:** The checker only fetches http(s).
- **Effect on readers:** The checker did not request it. Whether other tools can read `ftp:`, `data:` and similar depends on what they support.
- **Fix:**
  1. Link an `https://` address.
- **Confirm:** The entry is an https URL.

### SAFE_BLOCKED_PORT

*Level: blocked*

- **Means:** A URL on a port other than 80 or 443.
- **Why it is checked:** The checker only connects to standard web ports so it cannot be used to probe other services.
- **Effect on readers:** The checker did not request it. Reachability on unusual ports depends on the reader's network and policy.
- **Fix:**
  1. Publish on a standard port, or link the public address.
- **Confirm:** The URL has no explicit port.

### SAFE_BLOCKED_CREDENTIALS

*Level: blocked*

- **Means:** A URL containing a user name or password.
- **Why it is checked:** The checker refuses such URLs so it never handles or forwards credentials.
- **Effect on readers:** The target was not requested. If the address appears in a public file, the credential may already be exposed — remove it and rotate it.
- **Fix:**
  1. Remove the credentials from the URL.
  2. Rotate the secret.
  3. Do not list pages that need authentication.
- **Confirm:** No `user:pass@` in any link.

### SAFE_BLOCKED_PRIVATE

*Level: blocked*

- **Means:** A host that resolves to a private, loopback, reserved or otherwise restricted address.
- **Why it is checked:** The checker refuses these to avoid reaching protected networks.
- **Effect on readers:** The request was blocked by address policy. Internal-only targets are usually unreachable from outside, but this code alone does not prove the target is dead for everyone.
- **Fix:**
  1. Link the public address of the page.
  2. To check an internal site locally: `validate_llms_txt.py <url> --allow-private`.
- **Confirm:** The host resolves to a public address.

### SAFE_BLOCKED_SELF

*Level: not a finding*

- **Means:** A link pointing at the checking service itself.
- **Why it is checked:** The checker does not fetch its own address.
- **Effect on readers:** The check could not complete; this does not indicate a problem with the file.
- **Fix:**
  1. Confirm the intended target was entered.
- **Confirm:** —

### SAFE_BLOCKED_HOST

*Level: not a finding*

- **Means:** A request refused by an application-level allow-list before it was sent.
- **Why it is checked:** Some features only fetch from listed sources.
- **Effect on readers:** The check could not complete; this does not indicate a problem with the file.
- **Fix:**
  1. Nothing to fix in the file.
- **Confirm:** —

### SAFE_BLOCKED

*Level: unconfirmed*

- **Means:** A link whose fetch was blocked by policy, exceeded redirects, or whose follow-up request did not finish.
- **Why it is checked:** Records links that could not be confirmed, for whatever reason.
- **Effect on readers:** The link's state is unconfirmed; it may be a policy block, a redirect limit or an interrupted re-check. It cannot be called dead on this basis.
- **Fix:**
  1. Open the link yourself.
  2. If it is an internal or non-http address, link the public https page.
- **Confirm:** The link is reported reachable on the next check.

## Advice — editorial, not in the proposal

Suggestions. They never change the spec verdict and a file may ignore all of them and still be valid.

### ADVICE_SUMMARY_MISSING

*Level: advice*

- **Means:** No summary blockquote.
- **Why it is checked:** A summary lets a reader judge relevance before reading the entries.
- **Effect on readers:** Editorial advice, not a proposal rule: without a summary a reader infers the purpose from the title, text and entries.
- **Fix:**
  1. Add `> one or two specific sentences` under the H1 — or leave it out if nothing specific can be said.
- **Confirm:** The advice is gone.

### ADVICE_NO_SECTIONS

*Level: advice*

- **Means:** Entries are not grouped under H2 sections.
- **Why it is checked:** Grouping lets a reader take only the group relevant to its task.
- **Effect on readers:** Editorial advice, not a proposal rule: a flat list has no topical navigation.
- **Fix:**
  1. Group entries under `## Docs`, `## API`, `## Examples` or similar.
- **Confirm:** At least one H2 exists.

### ADVICE_ENTRY_NO_DESCRIPTION

*Level: advice*

- **Means:** Some entries have no `: description`.
- **Why it is checked:** A description helps a reader decide whether to open the page.
- **Effect on readers:** Editorial advice, not a proposal rule: with only a title there is less to go on, and the reader may have to open the page to find out.
- **Fix:**
  1. Add `: what this page covers` after the link — specific, not a repeat of the title.
- **Confirm:** The count drops.

### ADVICE_RELATIVE_URL

*Level: advice*

- **Means:** Some entries are not absolute http(s) URLs (relative paths, or schemes such as `mailto:`).
- **Why it is checked:** Flags entries that need a base address or another protocol to be used.
- **Effect on readers:** Editorial advice, not a proposal rule: a relative address must be resolved against the file's address and a non-http(s) one needs protocol support; whether that works depends on the reader.
- **Fix:**
  1. Write full `https://` URLs.
  2. Move contact addresses (`mailto:`) into the text above the first H2.
- **Confirm:** Every entry starts with `https://`.
