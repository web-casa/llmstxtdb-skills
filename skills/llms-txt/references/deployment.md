# Serving llms.txt

The file is static text. Deployment problems are almost always one of: it is not where the server looks for static files, an application route answers for it, or it is served with the wrong type.

## Where to put it

| Stack | Location | Served at |
| --- | --- | --- |
| Next.js | `public/llms.txt` | `/llms.txt` |
| Astro, Nuxt, Vite (React/Vue/Svelte), Remix | `public/llms.txt` | `/llms.txt` |
| SvelteKit, Gatsby, Hugo, Docusaurus | `static/llms.txt` | `/llms.txt` |
| Jekyll, Eleventy, plain HTML | site root (make sure it is copied to the output) | `/llms.txt` |
| MkDocs | `docs/llms.txt` | `/llms.txt` |
| VitePress | `docs/public/llms.txt` | `/llms.txt` |
| WordPress | web root next to `wp-config.php`, or a plugin/route that outputs it | `/llms.txt` |
| Express, Fastify, Django, Rails, Laravel | the static directory, or an explicit route | `/llms.txt` |

Check the framework's current docs if the project is on an unusual version; the principle is always "the directory copied verbatim to the site root".

Sub-path files (`/docs/llms.txt`) go in the matching sub-directory of the same static folder.

If the file is generated at build time (from a docs tree or CMS), generate it **into** that directory during the build, so previews and production serve the same thing.

## Content type

`text/plain; charset=utf-8` or `text/markdown; charset=utf-8`. Static hosts already do this for `.txt`. Set it explicitly when a route produces the file:

```js
// Next.js app router: app/llms.txt/route.ts
export async function GET() {
  const body = await buildLlmsTxt();
  return new Response(body, { headers: { "content-type": "text/plain; charset=utf-8" } });
}
```

```python
# Django
def llms_txt(request):
    return HttpResponse(build_llms_txt(), content_type="text/plain; charset=utf-8")
```

## The single-page-app trap

Symptom: `curl https://example.com/llms.txt` returns status 200 and a body starting with `<!doctype html>`. A catch-all rule is sending every unknown path to `index.html`. Either the file is missing from the deployed output, or a routing rule answers before the file is looked up.

Two things have to be true, and the snippets below give both:

1. when the file exists, it is served as a file;
2. when it does **not** exist, the answer is **404** — not the app shell with status 200. A site that answers 200 for everything makes every "does the file exist?" check meaningless, and hides a broken deploy.

A generic "try the file, else the app" rule satisfies the first point only. Handle `/llms.txt` explicitly, ahead of the catch-all:

```nginx
# Nginx
location = /llms.txt {
    default_type text/plain;
    charset utf-8;
    try_files /llms.txt =404;        # the file, or a real 404 - never the app
}
location / {
    try_files $uri $uri/ /index.html;   # the single-page app, for everything else
}
```

```caddy
# Caddy
example.com {
    root * /srv/site

    handle /llms.txt {
        file_server                  # answers 404 itself when the file is missing
    }
    handle {
        try_files {path} /index.html
        file_server
    }
}
```

```toml
# netlify.toml - order matters; a file in the publish directory wins over both rules
[[redirects]]
  from = "/llms.txt"
  to = "/404.html"                   # needs a 404.html in the publish directory
  status = 404

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

```apache
# Apache .htaccess
RewriteEngine On

# /llms.txt: the file if it exists, otherwise 404 - never the app
RewriteCond %{REQUEST_FILENAME} !-f
RewriteRule ^llms\.txt$ - [R=404,L]

# everything else: existing files as they are, the rest to the app
RewriteCond %{REQUEST_FILENAME} -f
RewriteRule ^ - [L]
RewriteRule ^ /index.html [L]
```

On platforms with their own routing layer (Vercel, Cloudflare Pages, Firebase Hosting and similar) check three things, in this order: the file is in the build output; no rewrite that runs *before* the filesystem lookup covers `/llms.txt` (in Next.js, `beforeFiles` rewrites and Middleware/Proxy both run first); the SPA fallback is declared so that it applies only after the file lookup. Do not assume "static files always win" — it depends on how the rules are declared.

## Redirects

One hop is fine (`http`→`https`, apex→`www`). Chains break things: `http://example.com` → `https://example.com` → `https://www.example.com` → `https://docs.example.com`. Request the final URL directly and link that one everywhere. If the docs moved to another host, the file should live on the host the links point to.

## Authentication, firewalls, bot rules

- The file must be fetchable without cookies or tokens. If the docs are private, a public llms.txt serves no purpose.
- A web application firewall or bot-protection rule that challenges non-browser clients blocks the very readers the file is for. Allow plain `GET /llms.txt` (and the linked `.md` pages) through.
- Rate limits on documentation paths should tolerate a reader fetching a few dozen pages in a row.
- Never put credentials in the URL of the file or of any link in it. A URL like `https://user:pass@host/…` exposes the secret to everyone who reads the file.

## Caching

Give it an ordinary short cache lifetime (minutes to an hour) and purge on deploy. A stale llms.txt listing pages that were removed is the most common source of dead links.

## Verify after deploying

```bash
curl -sS -o /dev/null -w '%{http_code} %{content_type} %{num_redirects} redirect(s) %{size_download} bytes\n' -L https://example.com/llms.txt
curl -sS https://example.com/llms.txt | head -n 3
python3 scripts/validate_llms_txt.py https://example.com/llms.txt --check-links
```

Expected: `200`, a text type, at most one redirect, a few kilobytes, and a first line starting with `# `.

To check a server on localhost or an internal host, add `--allow-private`; the validator refuses private addresses by default.
