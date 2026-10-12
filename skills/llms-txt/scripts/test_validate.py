#!/usr/bin/env python3
"""Self-tests for validate_llms_txt.py. Standard library only; no external network.

  python3 test_validate.py            run everything
  python3 test_validate.py --write-divergent   rewrite fixtures/divergent/expected.script.json

Fixtures:
  fixtures/strict/     this script and the llmstxtdb web checker must agree exactly
                       (expected.json is generated from the checker's engine)
  fixtures/divergent/  known differences; each side pins its own expectation
                       (expected.engine.json / expected.script.json) and the reason is
                       documented in references/spec.md
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_llms_txt as v  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
SCRIPT = os.path.join(HERE, "validate_llms_txt.py")


def read(kind: str, name: str) -> str:
    with open(os.path.join(FIXTURES, kind, name), encoding="utf-8", newline="") as f:
        return f.read()


def load(kind: str, name: str) -> dict:
    with open(os.path.join(FIXTURES, kind, name), encoding="utf-8") as f:
        return json.load(f)


def counts(text: str) -> dict:
    return v.code_counts(v.summarize(text))


def fixture_names(kind: str) -> list:
    return sorted(n for n in os.listdir(os.path.join(FIXTURES, kind)) if n.endswith(".txt"))


class StrictFixtures(unittest.TestCase):
    """Same verdict, same per-code counts, same advice as the web checker."""

    def test_every_fixture_has_an_expectation_and_matches(self):
        expected = load("strict", "expected.json")
        names = fixture_names("strict")
        self.assertEqual(sorted(expected), names, "fixture files and expected.json are out of sync")
        self.assertGreaterEqual(len(names), 30)
        for name in names:
            with self.subTest(fixture=name):
                self.assertEqual(counts(read("strict", name)), expected[name])

    def test_fixtures_cover_every_code_the_script_can_emit(self):
        expected = load("strict", "expected.json")
        spec = {k.split("/")[0] for e in expected.values() for k in e["spec"]}
        advice = {k for e in expected.values() for k in e["advice"]}
        self.assertEqual(spec, {"SPEC_H1_MISSING", "SPEC_H1_MULTIPLE", "SPEC_SUMMARY_EMPTY", "SPEC_SECTION_DEPTH", "SPEC_ENTRY_NOT_LINK"})
        self.assertEqual(advice, {"ADVICE_SUMMARY_MISSING", "ADVICE_NO_SECTIONS", "ADVICE_ENTRY_NO_DESCRIPTION", "ADVICE_RELATIVE_URL"})
        self.assertEqual({e["verdict"] for e in expected.values()}, {"PASS", "WARN", "FAIL"})


class DivergentFixtures(unittest.TestCase):
    """Known differences stay known: both sides are pinned and the difference is real."""

    def test_script_side_matches_and_really_differs_from_engine(self):
        engine = load("divergent", "expected.engine.json")
        script = load("divergent", "expected.script.json")
        names = fixture_names("divergent")
        self.assertEqual(sorted(engine), names)
        self.assertEqual(sorted(script), names)
        for name in names:
            with self.subTest(fixture=name):
                self.assertEqual(counts(read("divergent", name)), script[name])
                self.assertNotEqual(script[name], engine[name], "no longer divergent: move this fixture to strict/")

    def test_every_divergence_is_documented(self):
        with open(os.path.join(HERE, "..", "references", "spec.md"), encoding="utf-8") as f:
            doc = f.read()
        for name in fixture_names("divergent"):
            self.assertIn(name, doc, "%s is not explained in references/spec.md" % name)


class ParserDetails(unittest.TestCase):
    def test_positions(self):
        r = v.summarize("# A\n\n>\n\n# B\n\n### deep\n\n- plain\n- [x](https://e.example/x): d\n")
        by = {i["code"]: i["line"] for i in r["spec"]["issues"]}
        self.assertEqual(by, {"SPEC_H1_MULTIPLE": 5, "SPEC_SUMMARY_EMPTY": 3, "SPEC_SECTION_DEPTH": 7, "SPEC_ENTRY_NOT_LINK": 9})
        self.assertEqual(r["spec"]["verdict"], "FAIL")

    def test_verdict_levels(self):
        self.assertEqual(v.summarize("# T\n\n> s\n\n## D\n\n- [a](https://e.example/a): d\n")["spec"]["verdict"], "PASS")
        self.assertEqual(v.summarize("# T\n\n## D\n\n- plain\n")["spec"]["verdict"], "WARN")
        self.assertEqual(v.summarize("no title\n")["spec"]["verdict"], "FAIL")

    def test_entries_deduplicate_by_normalized_url(self):
        doc = v.parse_llms_txt("# T\n\n- [a](https://E.example:443/p#x): one\n- [b](HTTPS://e.example/p): two\n")
        self.assertEqual(len(doc["entries"]), 1)
        self.assertEqual(doc["entries"][0]["occurrences"], 2)
        self.assertEqual(doc["entries"][0]["url"], "https://e.example/p")

    def test_normalize_url(self):
        self.assertEqual(v.normalize_url("HTTP://Example.COM:80"), "http://example.com/")
        self.assertEqual(v.normalize_url("https://example.com:8443/a?b=1#c"), "https://example.com:8443/a?b=1")
        for bad in ("/docs/a", "docs/a.md", "mailto:a@b.example", "ftp://x.example/a", "https://", ""):
            self.assertIsNone(v.normalize_url(bad), bad)

    def test_advice_is_always_marked_non_standard(self):
        r = v.summarize("# T\n\n- [a](/rel)\n")
        self.assertEqual({a["code"] for a in r["advice"]["items"]}, {"ADVICE_SUMMARY_MISSING", "ADVICE_NO_SECTIONS", "ADVICE_ENTRY_NO_DESCRIPTION", "ADVICE_RELATIVE_URL"})
        self.assertTrue(all(a["nonStandard"] is True for a in r["advice"]["items"]))
        self.assertEqual(r["spec"]["verdict"], "PASS")  # advice never changes the spec verdict

    def test_large_input_is_linear_enough(self):
        text = "# T\n\n> s\n\n## D\n\n" + "".join("- [e%d](https://e.example/%d): d\n" % (i, i) for i in range(20000))
        start = time.monotonic()
        r = v.summarize(text)
        self.assertLess(time.monotonic() - start, 30, "generous bound: a quadratic parser would take minutes")
        self.assertEqual(r["metrics"]["entries"], 20000)

    def test_adversarial_inline_syntax_stays_linear(self):
        # Each of these made an earlier, regex-based scanner rescan the rest of the text for
        # every "[" or backtick. Doubling the input must not quadruple the time.
        def shapes(n):
            return [
                "# T\n\n- " + "[" * n,
                "# T\n\n- " + "[a](" * (n // 4),
                "# T\n\n- " + "[a](x \"" * (n // 7),
                "# T\n\n- " + "![" * (n // 2),
                "# T\n\n- " + "` x " * (n // 4),
                "# " + "[a](" * (n // 4),
                "# T\n\n- [a](" + "(" * (n // 2) + ")" * (n // 2) + ")",
                # long runs of spaces: patterns that backtrack over them are quadratic
                "# T" + " " * n + "x",
                "# T\n\n<a " + " " * n + "x",
                "# T\n\n- [a](x " + " " * n + "y)",
                "# T\n\n[a]: x" + " " * n + "y",
                "# T\n\n-" + " " * n + "x",
                "# T\n\n>" + " " * n + "x",
                "# T\n\n- [a](x \"" + "y" * n,
                "# T\n\n- " + "[a](b(c) \"" * (n // 12),
                "# T\n\n- " + "[a](<b \"" * (n // 9),
                "# T\n\n<a " + "b=\"c\" " * (n // 6) + "x",
            ]

        def cost(n):
            start = time.monotonic()
            for text in shapes(n):
                v.summarize(text)
            return time.monotonic() - start

        def one(text):
            best = None
            for _ in range(3):  # best of three: a single sample is at the mercy of the scheduler
                start = time.monotonic()
                v.summarize(text)
                took = time.monotonic() - start
                best = took if best is None else min(best, took)
            return best

        cost(20000)  # warm up
        # Shape by shape, so one regression cannot hide behind the others.
        for idx, (small_text, big_text) in enumerate(zip(shapes(100000), shapes(400000))):
            small, big = one(small_text), one(big_text)
            self.assertLess(big, 20, "shape %d" % idx)
            self.assertLess(big, max(small, 0.05) * 12, "shape %d: 4x the input took %.2fs vs %.2fs" % (idx, big, small))

    def test_titles_with_stray_parentheses(self):
        # A quoted title may contain an unbalanced parenthesis; the link is still a link.
        for title in ('"draft )"', '"draft ("', "'a ) b'", '"(both)"'):
            with self.subTest(title=title):
                r = v.summarize("# T\n\n> s\n\n## D\n\n- [a](https://e.example/a %s): d\n" % title)
                self.assertEqual((r["metrics"]["entries"], r["spec"]["verdict"]), (1, "PASS"))
                self.assertEqual(r["advice"]["items"], [])
        # ...also when the address itself has balanced parentheses, is separated by a wide gap,
        # or is written in angle brackets (the link text must stay the title, not the URL).
        for item, url in (('[a](https://e.example/a(b) "draft )")', "https://e.example/a(b)"),
                          ('[a](https://e.example/a         "draft )")', "https://e.example/a"),
                          ('[a](<https://e.example/a> "draft )")', "https://e.example/a"),
                          ('[a](<https://e.example/with space> "draft (")', "https://e.example/with space"),
                          # escaped parentheses in the address are literal characters, not nesting
                          ('[a](https://e.example/a\\(b\\) "draft )")', "https://e.example/a(b)"),
                          ('[a](https://e.example/a\\) "draft )")', "https://e.example/a)"),
                          ('[a](https://e.example/a\\( "draft (")', "https://e.example/a(")):
            with self.subTest(item=item):
                found = v._find_link(item + ": d", {})
                self.assertEqual(found, ("a", url))

    def test_atx_heading_forms(self):
        for line, expected in (("# Title", (1, "Title")), ("## Title ##", (2, "Title")), ("# Title#", (1, "Title#")),
                               ("###   Spaced   ", (3, "Spaced")), ("#", (1, "")), ("## #", (2, "")), ("# a # b #", (1, "a # b")),
                               ("   # indented", (1, "indented"))):
            m = v._atx(line)
            self.assertIsNotNone(m, line)
            self.assertEqual((m.depth, m.title), expected, line)
        for line in ("#NoSpace", "####### seven", "    # code", "text # not"):
            self.assertIsNone(v._atx(line), line)

    def test_lone_html_tag_detection(self):
        for line in ("<x-widget>", "</custom-tag>", "<a href=\"u\">", "  <br/>", "</a >", "<a title=\">\">", "<a b='<' c=d e>",
                     "<img src=x />", "<a   href = \"u\"   >  "):
            self.assertTrue(v._is_lone_html_tag(line), line)
        for line in ("<a href=\"u\">text</a>", "text <b>", "<>", "< a>", "<a", "    <x-widget>", "<a>b", "<a /garbage>",
                     "<a href=\"unterminated>", "<a href=>", "<a\"x\">", "</a b>", "<a b=\"c\"d>"):
            self.assertFalse(v._is_lone_html_tag(line), line)
        # Consequences for structure: a real tag swallows the following line, a broken one does not.
        self.assertEqual(v.parse_llms_txt("<a title=\">\">\n# T\n")["h1_count"], 0)
        self.assertEqual(v.parse_llms_txt("<a /garbage>\n# T\n")["h1_count"], 1)
        self.assertEqual(v.parse_llms_txt("<a href=\"unterminated>\n# T\n")["h1_count"], 1)

    def test_deeply_nested_brackets_do_not_recurse_without_bound(self):
        depth = 5000
        r = v.summarize("# T\n\n- " + "[" * depth + "x" + "]" * depth + "(https://e.example/x): d\n")
        self.assertEqual(r["metrics"]["entries"], 1)


class AddressRules(unittest.TestCase):
    def test_public_and_non_public(self):
        for ip in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(v.is_public_ip(ip), ip)
        for ip in ("127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
                   "224.0.0.1", "240.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
                   "2002:7f00:1::", "not-an-ip"):
            self.assertFalse(v.is_public_ip(ip), ip)

    def test_url_shape(self):
        for url, code in (("ftp://e.example/a", "SAFE_BLOCKED_SCHEME"), ("file:///etc/passwd", "SAFE_BLOCKED_SCHEME"),
                          ("https://user:pw@e.example/a", "SAFE_BLOCKED_CREDENTIALS"), ("https://user@e.example/a", "SAFE_BLOCKED_CREDENTIALS"),
                          ("https:///nohost", "INVALID_URL")):
            with self.assertRaises(v.FetchError) as cm:
                v.check_url_shape(url)
            self.assertEqual(cm.exception.code, code, url)
        v.check_url_shape("https://e.example/a")

    def test_any_non_public_address_blocks_the_host(self):
        mixed = lambda host, port: ["93.184.216.34", "10.0.0.1"]  # noqa: E731
        with self.assertRaises(v.FetchError) as cm:
            v.resolve_checked("mixed.example", 443, False, resolver=mixed)
        self.assertEqual(cm.exception.code, "SAFE_BLOCKED_PRIVATE")
        self.assertEqual(v.resolve_checked("mixed.example", 443, True, resolver=mixed), "93.184.216.34")


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        route = self.server.routes.get(self.path.split("?")[0])
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        route(self)


class _QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # clients hang up early on purpose in these tests
        pass


def serve(routes: dict):
    srv = _QuietServer(("127.0.0.1", 0), _Handler)
    srv.routes = routes
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def respond(body: bytes, ctype="text/plain; charset=utf-8", status=200, headers=None):
    def h(req):
        req.send_response(status)
        req.send_header("Content-Type", ctype)
        req.send_header("Content-Length", str(len(body)))
        for k, val in (headers or {}).items():
            req.send_header(k, val)
        req.end_headers()
        req.wfile.write(body)
    return h


def redirect(to: str):
    def h(req):
        req.send_response(302)
        req.send_header("Location", to)
        req.send_header("Content-Length", "0")
        req.end_headers()
    return h


GOOD = b"# T\n\n> s\n\n## D\n\n- [a](https://e.example/a): d\n"


class FetchRules(unittest.TestCase):
    """In-process: the redirect loop with an injected resolver / public check."""

    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve({
            "/llms.txt": respond(GOOD),
            "/hop": redirect("/llms.txt"),
            "/to-internal": redirect("http://internal.example/secret"),
            "/to-file": redirect("file:///etc/passwd"),
            "/to-creds": redirect("http://u:p@127.0.0.1/x"),
            "/loop": redirect("/loop"),
            "/gzip": respond(b"\x1f\x8b\x08\x00", headers={"Content-Encoding": "gzip"}),
            "/big": respond(b"x" * 5000),
        })
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def fetch(self, path, **kw):
        # "public.example" stands for a public host that happens to be served locally;
        # "internal.example" resolves to a private address.
        table = {"public.example": ["127.0.0.1"], "internal.example": ["10.0.0.9"]}
        resolver = lambda host, port: table[host]  # noqa: E731
        public = lambda ip: ip == "127.0.0.1"  # noqa: E731
        return v.fetch_follow("http://public.example:%d%s" % (self.port, path), kw.pop("max_bytes", 100000), False, 5,
                              resolver=resolver, public_check=public, **kw)

    def test_ok_and_redirect_chain(self):
        r = self.fetch("/hop")
        self.assertEqual((r["status"], r["body"].encode(), len(r["redirects"])), (200, GOOD, 1))
        self.assertTrue(r["finalUrl"].endswith("/llms.txt"))

    def test_redirect_to_private_address_is_blocked(self):
        with self.assertRaises(v.FetchError) as cm:
            self.fetch("/to-internal")
        self.assertEqual(cm.exception.code, "SAFE_BLOCKED_PRIVATE")

    def test_redirect_to_other_scheme_or_credentials_is_blocked(self):
        with self.assertRaises(v.FetchError) as cm:
            self.fetch("/to-file")
        self.assertEqual(cm.exception.code, "SAFE_BLOCKED_SCHEME")
        with self.assertRaises(v.FetchError) as cm:
            self.fetch("/to-creds")
        self.assertEqual(cm.exception.code, "SAFE_BLOCKED_CREDENTIALS")

    def test_redirect_limit(self):
        with self.assertRaises(v.FetchError) as cm:
            self.fetch("/loop")
        self.assertEqual(cm.exception.code, "TOO_MANY_REDIRECTS")

    def test_encoded_response_is_rejected_not_decoded(self):
        with self.assertRaises(v.FetchError) as cm:
            self.fetch("/gzip")
        self.assertEqual(cm.exception.code, "ENCODED_RESPONSE")

    def test_body_is_capped(self):
        r = self.fetch("/big", max_bytes=1000)
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["body"]), 1000)

    def test_private_target_needs_explicit_opt_in(self):
        with self.assertRaises(v.FetchError) as cm:
            v.fetch_follow("%s/llms.txt" % self.base, 1000, False, 5)
        self.assertEqual(cm.exception.code, "SAFE_BLOCKED_PRIVATE")
        self.assertEqual(v.fetch_follow("%s/llms.txt" % self.base, 100000, True, 5)["status"], 200)


def slow(kind: str):
    """Handlers that never finish quickly: the parent must cut them off."""
    def h(req):
        try:
            if kind == "headers":
                req.wfile.write(b"HTTP/1.1 200 OK\r\n")
                for _ in range(600):
                    req.wfile.write(b"X-Slow: 1\r\n")
                    req.wfile.flush()
                    time.sleep(0.05)
            elif kind == "body":
                req.send_response(200)
                req.send_header("Content-Type", "text/plain")
                req.send_header("Content-Length", "100000")
                req.end_headers()
                for _ in range(600):
                    req.wfile.write(b"x")
                    req.wfile.flush()
                    time.sleep(0.05)
            elif kind == "chunked":
                req.send_response(200)
                req.send_header("Content-Type", "text/plain")
                req.send_header("Transfer-Encoding", "chunked")
                req.end_headers()
                for _ in range(600):
                    req.wfile.write(b"1\r\nx\r\n")
                    req.wfile.flush()
                    time.sleep(0.05)
            else:  # "silent": accept and say nothing
                time.sleep(30)
        except OSError:
            pass
    return h


class Deadlines(unittest.TestCase):
    """Subprocess path: the absolute deadline is enforced by killing the worker."""

    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve({
            "/llms.txt": respond(GOOD),
            "/slow-headers": slow("headers"), "/slow-body": slow("body"), "/slow-chunked": slow("chunked"), "/silent": slow("silent"),
            "/huge": respond(b"y" * (v.MAX_BODY_BYTES + 5000)),
        })

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def timed(self, path, deadline=1.0):
        start = time.monotonic()
        r = v.fetch(self.base + path, v.Budget(), allow_private=True, request_deadline=deadline)
        return r, time.monotonic() - start

    def test_normal_fetch_through_the_worker(self):
        r, _ = self.timed("/llms.txt", 10)
        self.assertEqual((r["ok"], r["status"], r["body"].encode()), (True, 200, GOOD))

    def test_slow_responses_are_cut_off_at_the_deadline(self):
        for path in ("/slow-headers", "/slow-body", "/slow-chunked", "/silent"):
            with self.subTest(path=path):
                r, took = self.timed(path, 1.0)
                self.assertEqual((r["ok"], r["error"]), (False, "TIMEOUT"))
                # These servers would keep the connection busy for 30 s. Returning in a fraction of
                # that proves the worker was killed; the margin absorbs slow process start-up on CI.
                self.assertLess(took, 12.0)

    def test_global_deadline_and_request_budget(self):
        spent = v.Budget(seconds=0)
        self.assertEqual(v.fetch(self.base + "/llms.txt", spent, allow_private=True)["error"], "TIMEOUT")
        none_left = v.Budget(requests=0)
        self.assertEqual(v.fetch(self.base + "/llms.txt", none_left, allow_private=True)["error"], "BUDGET_EXCEEDED")
        one = v.Budget(requests=1)
        self.assertTrue(v.fetch(self.base + "/llms.txt", one, allow_private=True)["ok"])
        self.assertEqual(v.fetch(self.base + "/llms.txt", one, allow_private=True)["error"], "BUDGET_EXCEEDED")

    def test_redirect_hops_count_against_the_request_budget(self):
        srv, base = serve({"/a": redirect("/b"), "/b": redirect("/c"), "/c": respond(GOOD)})
        try:
            b = v.Budget(requests=10)
            r = v.fetch(base + "/a", b, allow_private=True)
            self.assertEqual((r["ok"], r["requests"]), (True, 3))
            self.assertEqual(b.requests_left, 7)  # three requests, not one
            tight = v.Budget(requests=2)
            r = v.fetch(base + "/a", tight, allow_private=True)
            self.assertEqual((r["ok"], r["error"]), (False, "BUDGET_EXCEEDED"))  # the third hop is not sent
            self.assertEqual(tight.requests_left, 0)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_killed_worker_is_charged_the_worst_case(self):
        b = v.Budget(requests=10)
        v.fetch(self.base + "/silent", b, allow_private=True, request_deadline=1.0)
        self.assertEqual(b.requests_left, 10 - (v.MAX_REDIRECTS + 1))

    def test_oversized_body_is_truncated_and_flagged(self):
        r, _ = self.timed("/huge", 10)
        self.assertTrue(r["ok"])
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["body"]), v.MAX_BODY_BYTES)

    def test_private_address_is_refused_without_the_flag(self):
        r = v.fetch(self.base + "/llms.txt", v.Budget())
        self.assertEqual((r["ok"], r["error"]), (False, "SAFE_BLOCKED_PRIVATE"))

    def test_worker_ignores_argv_and_only_reads_whitelisted_fields(self):
        # Extra arguments do not turn worker mode on; unknown stdin fields are ignored.
        p = subprocess.run([sys.executable, SCRIPT, v.WORKER_FLAG, "--allow-private"], input=b"{}", capture_output=True, timeout=20)
        self.assertNotEqual(p.returncode, 0)  # argparse rejects it: not worker mode
        job = json.dumps({"url": self.base + "/llms.txt", "allow_private": "yes", "max_bytes": 10 ** 12, "shell": "rm -rf /"})
        p = subprocess.run([sys.executable, SCRIPT, v.WORKER_FLAG], input=job.encode(), capture_output=True, timeout=20)
        out = json.loads(p.stdout)
        self.assertEqual(out["error"], "SAFE_BLOCKED_PRIVATE")  # "yes" is not True

    def test_worker_clamps_untrusted_numbers(self):
        def worker(job):
            p = subprocess.run([sys.executable, SCRIPT, v.WORKER_FLAG], input=json.dumps(job).encode(), capture_output=True, timeout=30)
            return json.loads(p.stdout)
        # A negative size must not turn into "read everything" (read(-1)).
        out = worker({"url": self.base + "/huge", "allow_private": True, "max_bytes": -2})
        self.assertTrue(out["ok"])
        self.assertLessEqual(len(out["body"]), v.MAX_BODY_BYTES)
        self.assertTrue(out["truncated"])
        out = worker({"url": self.base + "/llms.txt", "allow_private": True, "max_bytes": 5, "timeout": -1, "max_requests": 10 ** 9})
        self.assertEqual((out["ok"], out["body"], out["truncated"]), (True, "# T\n\n", True))
        for bad in ([1, 2], "x", {"url": 5}, {"url": "h" * 9000}):
            self.assertEqual(worker(bad)["ok"], False)
        p = subprocess.run([sys.executable, SCRIPT, v.WORKER_FLAG], input=b"x" * 200000, capture_output=True, timeout=30)
        self.assertEqual(json.loads(p.stdout)["error"], "INVALID_URL")  # oversized job is refused, not parsed

    def test_failures_before_any_request_cost_nothing(self):
        b = v.Budget(requests=10)
        r = v.fetch(self.base + "/llms.txt", b)  # refused: private address, nothing was sent
        self.assertEqual((r["error"], r["requests"], b.requests_left), ("SAFE_BLOCKED_PRIVATE", 0, 10))


class CommandLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = b"<!doctype html><html><head><title>App</title></head><body><div id=\"root\"></div></body></html>"
        cls.srv, cls.base = serve({
            "/llms.txt": respond(b"# T\n\n> s\n\n## D\n\n- [ok](/ok.md): fine\n- [gone](/gone.md): missing\n- plain\n"),
            "/ok.md": respond(b"# ok\n"), "/spa/llms.txt": respond(html, "text/html"),
            "/empty.txt": respond(b""),
        })

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def cli(self, *args):
        p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, timeout=90)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_local_file_and_exit_codes(self):
        code, out, _ = self.cli(os.path.join(FIXTURES, "strict", "valid-minimal.txt"))
        self.assertEqual(code, 0)
        self.assertIn("Spec (llmstxt.org proposal): PASS", out)
        code, out, _ = self.cli(os.path.join(FIXTURES, "strict", "h1-missing.txt"))
        self.assertEqual(code, 1)
        self.assertIn("SPEC_H1_MISSING", out)
        code, _, err = self.cli("/no/such/file.txt")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        self.assertEqual(self.cli("ftp://e.example/llms.txt")[0], 2)

    def test_json_output_keeps_the_three_parts_apart(self):
        code, out, _ = self.cli(os.path.join(FIXTURES, "strict", "relative-urls.txt"), "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(set(data) & {"spec", "advice", "metrics"}, {"spec", "advice", "metrics"})
        self.assertNotIn("usable", data)  # a local file has no deployment to observe
        self.assertNotIn("grade", data)
        self.assertNotIn("score", data)
        self.assertTrue(all(a["nonStandard"] for a in data["advice"]["items"]))

    def test_url_with_link_check(self):
        code, out, _ = self.cli(self.base + "/llms.txt", "--allow-private", "--check-links", "--json")
        data = json.loads(out)
        self.assertEqual(code, 1)  # one dead link
        self.assertEqual(data["usable"]["links"]["coverage"], {"total": 2, "sampled": 2, "completed": 2})
        self.assertEqual([d["url"] for d in data["usable"]["links"]["dead"]], [self.base + "/gone.md"])
        self.assertEqual(data["spec"]["verdict"], "WARN")

    def test_html_shell_is_reported_and_not_parsed_as_markdown(self):
        code, out, _ = self.cli(self.base + "/spa/llms.txt", "--allow-private", "--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual({c["code"]: c["verdict"] for c in data["usable"]["checks"]}["SPA_DETECTED"], "FAIL")
        self.assertNotIn("spec", data)

    def test_not_found_and_empty(self):
        code, out, _ = self.cli(self.base + "/missing.txt", "--allow-private", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["usable"]["checks"][0], {"code": "HTTP_STATUS", "verdict": "FAIL", "message": "HTTP 404"})
        code, out, _ = self.cli(self.base + "/empty.txt", "--allow-private", "--json")
        self.assertEqual({c["code"]: c["verdict"] for c in json.loads(out)["usable"]["checks"]}["FILE_SIZE"], "WARN")

    def test_runs_from_a_path_with_spaces(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp(prefix="llms txt skill ")
        try:
            shutil.copy(SCRIPT, os.path.join(d, "validate_llms_txt.py"))
            p = subprocess.run([sys.executable, os.path.join(d, "validate_llms_txt.py"), self.base + "/llms.txt", "--allow-private"], capture_output=True, timeout=60)
            self.assertIn(b"HTTP 200", p.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def write_divergent() -> None:
    out = {name: counts(read("divergent", name)) for name in fixture_names("divergent")}
    with open(os.path.join(FIXTURES, "divergent", "expected.script.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print("wrote expected.script.json for %d fixture(s)" % len(out))


if __name__ == "__main__":
    if "--write-divergent" in sys.argv:
        write_divergent()
    else:
        socket.setdefaulttimeout(30)
        unittest.main(verbosity=1)
