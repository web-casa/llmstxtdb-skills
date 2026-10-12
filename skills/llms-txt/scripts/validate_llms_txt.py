#!/usr/bin/env python3
"""Validate an llms.txt file against the llmstxt.org proposal.

Standard library only (Python 3.9+). Reports three separate things and never
mixes them:

  spec    what the llmstxt.org proposal actually requires (structure)
  usable  whether the deployed file can really be fetched and read (URL input only)
  advice  editorial suggestions that are NOT part of the proposal

Issue codes are the same ones the llmstxtdb web checker uses, so a local run
and an online report can be compared line by line.

Usage:
  validate_llms_txt.py PATH_OR_URL [--json] [--check-links] [--max-links N]
                                   [--allow-private] [--use-env-proxy]

Exit status: 0 = no spec/usable failure, 1 = at least one FAIL, 2 = could not run.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urljoin, urlsplit, urlunsplit

VERSION = "0.1.0"

# ----------------------------------------------------------------------------
# Limits (network). Every fetch runs in a child process that the parent kills
# at an absolute deadline: an in-process socket timeout cannot stop a server
# that keeps trickling bytes (one http.client read() loops over many recv()s).
# ----------------------------------------------------------------------------
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_DEADLINE_S = 10.0
GLOBAL_DEADLINE_S = 60.0
MAX_LINKS_DEFAULT = 20
MAX_REQUESTS = 30
LINK_BODY_BYTES = 2048
WORKER_FLAG = "--_fetch-worker"
USER_AGENT = "llmstxtdb-skill-validator/" + VERSION

# ============================================================================
# Part 1. Parsing (pure, no I/O)
# ============================================================================

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# Patterns here must not backtrack over long runs of spaces: lines can be megabytes long.
ATX_OPEN_RE = re.compile(r"^ {0,3}(#{1,6})(?=[ \t]|$)")


class _Atx:
    """Result of ATX heading recognition (kept as a tiny object so call sites read like a match)."""

    __slots__ = ("depth", "title")

    def __init__(self, depth: int, title: str):
        self.depth = depth
        self.title = title


def _atx(line: str):
    """`## Title ##` -> depth 2, "Title". String operations only (no regex over the title)."""
    m = ATX_OPEN_RE.match(line)
    if not m:
        return None
    rest = line[m.end():].strip(" \t")
    if rest.endswith("#"):
        body = rest.rstrip("#")
        if not body or body[-1] in " \t":  # a closing sequence must be preceded by a space
            rest = body.rstrip(" \t")
    return _Atx(len(m.group(1)), rest)
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
ITEM_RE = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])(?:([ \t]+)(.*)|[ \t]*)$")
QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
DEF_RE = re.compile(r"^ {0,3}\[((?:[^\[\]\\]|\\.)+)\]:[ \t]*<?([^\s>]+)>?(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$")
# HTML blocks (CommonMark): block-level tags may interrupt a paragraph and run to the next blank
# line; a comment runs to the line holding "-->"; any other complete tag only starts a block
# when it stands on its own line and no paragraph is open.
HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|"
    "fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|"
    "menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
)
HTML_BLOCK_RE = re.compile(r"^ {0,3}</?(?:%s)(?:[\s/>]|$)" % HTML_BLOCK_TAGS, re.I)
HTML_RAW_RE = re.compile(r"^ {0,3}<(?:script|pre|style|textarea)(?:[\s>]|$)", re.I)
HTML_RAW_END_RE = re.compile(r"</(?:script|pre|style|textarea)>", re.I)
HTML_COMMENT_RE = re.compile(r"^ {0,3}<!--")
HTML_DECL_RE = re.compile(r"^ {0,3}<(?:\?|![A-Z]|!\[CDATA\[)")
HTML_TAG_NAME_RE = re.compile(r"</?[A-Za-z][\w-]*")
INDENT4_RE = re.compile(r"^(?: {4}|\t)")


def _is_lone_html_tag(line: str) -> bool:
    """A complete open or closing tag alone on its line (CommonMark HTML block type 7).
    One left-to-right scan: `<name attr attr=value attr="v" attr='v' />` or `</name >`,
    followed only by spaces. Attribute values in quotes may contain `<` and `>`."""
    if INDENT4_RE.match(line):
        return False
    t = line.strip(" \t")
    n = len(t)
    m = HTML_TAG_NAME_RE.match(t)
    if not m:
        return False
    i = m.end()
    if t[1] == "/":  # closing tag: name, optional spaces, ">"
        while i < n and t[i] in " \t":
            i += 1
        return i == n - 1 and t[i] == ">"
    while True:
        had_space = False
        while i < n and t[i] in " \t":
            i += 1
            had_space = True
        if i >= n:
            return False
        if t[i] == ">":
            return i == n - 1
        if t[i] == "/":
            return i + 1 == n - 1 and t[i + 1] == ">"
        if not had_space:
            return False  # attributes must be separated from the name and from each other
        start = i
        while i < n and (t[i].isalnum() or t[i] in "_:.-"):
            i += 1
        if i == start or not (t[start].isalpha() or t[start] in "_:"):
            return False
        j = i
        while j < n and t[j] in " \t":
            j += 1
        if j < n and t[j] == "=":
            j += 1
            while j < n and t[j] in " \t":
                j += 1
            if j >= n:
                return False
            if t[j] in "\"'":
                end = t.find(t[j], j + 1)
                if end == -1:
                    return False
                i = end + 1
            else:
                k = j
                while k < n and t[k] not in " \t\"'=<>`":
                    k += 1
                if k == j:
                    return False
                i = k


def _html_block_end(lines: list, i: int, paragraph_open: bool):
    """If an HTML block starts at line i, return the index of the first line after it."""
    line = lines[i]
    n = len(lines)
    if HTML_RAW_RE.match(line):
        j = i
        while j < n and not HTML_RAW_END_RE.search(lines[j]):
            j += 1
        return min(j + 1, n)
    if HTML_COMMENT_RE.match(line):
        j = i
        while j < n and "-->" not in (lines[j][lines[j].index("<!--") + 4:] if j == i else lines[j]):
            j += 1
        return min(j + 1, n)
    if HTML_DECL_RE.match(line):
        end = "?>" if "<?" in line else "]]>" if "CDATA" in line else ">"
        j = i
        while j < n and end not in lines[j]:
            j += 1
        return min(j + 1, n)
    if HTML_BLOCK_RE.match(line) or (not paragraph_open and _is_lone_html_tag(line)):
        j = i
        while j < n and lines[j].strip():
            j += 1
        return j
    return None
INDENTED_RE = re.compile(r"^(?: {4,}|\t)")

AUTOLINK_RE = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]{0,2048})>")
LINK_TITLE_RE = re.compile(r"[ \t\n]+(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'|\([^)\n]{0,512}\))[ \t\n]*\)")
QUOTED_TITLE_RE = re.compile(r"[ \t\n]{1,64}(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}')[ \t\n]{0,64}\)")
LEADING_SEP_RE = re.compile(r"^[\s:：–-]+")
HTTP_RE = re.compile(r"^https?://", re.I)
MAX_DEST_CHARS = 2048  # a link destination longer than this is not a real URL


def _label(s: str) -> str:
    """Reference labels match case-insensitively with collapsed whitespace."""
    return re.sub(r"\s+", " ", s.strip()).lower()


# ---- inline scanning --------------------------------------------------------
# Everything below is a single pass (or O(n log n)) over the text. The input can be an
# arbitrary 2 MB response, so no helper may rescan the remainder for every "[" or "`".

def _code_spans(s: str) -> list:
    """(start, end, inner_start, inner_end) of code spans: a run of N backticks closes at the
    next run of exactly N backticks."""
    runs = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    by_len = {}
    for idx, (_pos, length) in enumerate(runs):
        by_len.setdefault(length, []).append(idx)
    cursor = {length: 0 for length in by_len}
    spans = []
    k = 0
    while k < len(runs):
        pos, length = runs[k]
        candidates = by_len[length]
        c = cursor[length]
        while c < len(candidates) and candidates[c] <= k:
            c += 1
        cursor[length] = c
        if c < len(candidates):
            close = candidates[c]
            cpos = runs[close][0]
            spans.append((pos, cpos + length, pos + length, cpos))
            k = close + 1
        else:
            k += 1
    return spans


def _mask_code(s: str) -> str:
    """Blank out code spans (same length), so link syntax inside code is not seen as a link."""
    spans = _code_spans(s)
    if not spans:
        return s
    parts, pos = [], 0
    for start, end, _a, _b in spans:
        parts.append(s[pos:start])
        parts.append(" " * (end - start))
        pos = end
    parts.append(s[pos:])
    return "".join(parts)


def _match_pairs(s: str, open_ch: str, close_ch: str) -> dict:
    """Matching positions for a bracket pair, backslash escapes honoured. One pass."""
    match, stack = {}, []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == open_ch:
            stack.append(i)
        elif c == close_ch and stack:
            match[stack.pop()] = i
        i += 1
    return match


def _balanced_parens(s: str, start: int, end: int, first_special: int) -> bool:
    """True if s[start:end] has no unescaped angle brackets and its unescaped parentheses are
    balanced. The common case (no special character at all) is answered from the precomputed
    index in O(1); otherwise one escape-aware scan from the start, bounded by MAX_DEST_CHARS."""
    if first_special >= end:
        return True
    depth, idx = 0, start
    while idx < end:
        ch = s[idx]
        if ch == "\\":
            idx += 2  # an escaped character is literal, whatever it is
            continue
        if ch in "<>":
            return False
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
        idx += 1
    return depth == 0


def _scan_links(s: str) -> list:
    """Inline constructs found by bracket matching (link text may nest brackets to any depth):
      ("link", start, end, text_start, text_end, dest)      [text](dest "title")
      ("image", start, end, ...)                            ![alt](src)   - not a link
      ("ref", start, end, text_start, text_end, label)      [text][label] / [text][] / [text]
    Outermost constructs only, in document order."""
    brackets = _match_pairs(s, "[", "]")
    parens = _match_pairs(s, "(", ")")
    out = []
    n = len(s)
    # For the quoted-title fallback: next whitespace at or after each position, and next
    # character that cannot be part of a bare destination. Both built in one reverse pass.
    next_ws = [n] * (n + 1)
    next_special = [n] * (n + 1)
    for idx in range(n - 1, -1, -1):
        ch = s[idx]
        next_ws[idx] = idx if ch in " \t\n" else next_ws[idx + 1]
        next_special[idx] = idx if ch in "()<>" else next_special[idx + 1]
    i = 0
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] != "[" or i not in brackets:
            i += 1
            continue
        j = brackets[i]
        image = i > 0 and s[i - 1] == "!"
        if j + 1 < n and s[j + 1] == "(" and (j + 1) in parens:
            close = parens[j + 1]
            k = j + 2
            while k < close and s[k] in " \t\n":
                k += 1
            dest = None
            if k < close and s[k] == "<":
                gt = s.find(">", k, min(close, k + MAX_DEST_CHARS))
                if gt != -1 and "\n" not in s[k:gt]:
                    tail = s[gt + 1:close] if close - gt <= 600 else None
                    if tail is not None and (not tail.strip() or LINK_TITLE_RE.fullmatch(tail + ")")):
                        dest = s[k + 1:gt]
            else:
                m = k
                limit = min(close, k + MAX_DEST_CHARS)
                while m < limit and s[m] not in " \t\n":
                    m += 1
                if m == close:
                    dest = s[k:close]
                elif m < limit and close - m <= 600 and (not s[m:close].strip() or LINK_TITLE_RE.fullmatch(s[m:close + 1])):
                    dest = s[k:m]
            if dest is not None:
                out.append(("image" if image else "link", i - 1 if image else i, close + 1, i + 1, j, dest))
                i = close + 1
                continue
        if j + 1 < n and s[j + 1] == "(":
            # Fallback: `(dest "title")` where the quoted title holds a stray parenthesis, which
            # throws the global pairing off. A destination (bare with balanced parentheses, or in
            # angle brackets), then a quoted title, then ")".
            k = j + 2
            while k < n and s[k] in " \t\n" and k - j < 66:
                k += 1
            dest, after = None, -1
            if k < n and s[k] == "<":
                gt = s.find(">", k, k + MAX_DEST_CHARS)
                if gt != -1 and "\n" not in s[k:gt] and "<" not in s[k + 1:gt]:
                    dest, after = s[k + 1:gt], gt + 1
            else:
                ws = next_ws[k]
                if k < ws <= k + MAX_DEST_CHARS and _balanced_parens(s, k, ws, next_special[k]):
                    dest, after = s[k:ws], ws
            if dest is not None:
                t = QUOTED_TITLE_RE.match(s, after)
                if t:
                    out.append(("image" if image else "link", i - 1 if image else i, t.end(), i + 1, j, dest))
                    i = t.end()
                    continue
        if not image:
            if j + 1 < n and s[j + 1] == "[" and (j + 1) in brackets:
                j2 = brackets[j + 1]
                label = s[j + 2:j2]
                out.append(("ref", i, j2 + 1, i + 1, j, label if label.strip() else s[i + 1:j]))
                i = j2 + 1
                continue
            out.append(("ref", i, j + 1, i + 1, j, s[i + 1:j]))
            i = j + 1
            continue
        i += 1
    return out


def _plain(s: str, definitions=None, _depth: int = 0) -> str:
    """Rough plain-text rendering of inline Markdown (enough to compare titles and to tell
    whether anything is left besides the link). Images are dropped, links and resolvable
    references become their text, code spans become their content."""
    parts, pos = [], 0
    for kind, start, end, t0, t1, extra in _scan_links(_mask_code(s)):
        if kind == "ref" and (definitions is None or _label(extra) not in definitions):
            continue  # not a link: leave the brackets as written
        parts.append(s[pos:start])
        if kind != "image":
            inner = s[t0:t1]
            # Nested constructs inside link text: bounded recursion (deeper nesting is left as written).
            parts.append(_plain(inner, definitions, _depth + 1) if "[" in inner and _depth < 6 else inner)
        pos = end
    parts.append(s[pos:])
    s = "".join(parts)
    s = AUTOLINK_RE.sub(lambda m: m.group(1), s)
    spans = _code_spans(s)
    if spans:
        parts, pos = [], 0
        for start, end, a, b in spans:
            parts.append(s[pos:start])
            parts.append(s[a:b])
            pos = end
        parts.append(s[pos:])
        s = "".join(parts)
    s = re.sub(r"\*\*|__|\*|_", "", s)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>])", r"\1", s)
    return s


def normalize_url(raw: str):
    """Mirror of the checker's URL normalization. Returns None when it would fail
    (relative reference, non-http(s) scheme, unparsable) - the caller keeps the raw value."""
    try:
        p = urlsplit(raw.strip())
    except ValueError:
        return None
    scheme = p.scheme.lower()
    if scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    if ":" in host:  # IPv6 literal
        host = "[" + host + "]"
    try:
        port = p.port
    except ValueError:
        return None
    netloc = host
    if p.username is not None:
        netloc = p.username + (":" + p.password if p.password is not None else "") + "@" + netloc
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc += ":" + str(port)
    return urlunsplit((scheme, netloc, p.path or "/", p.query, ""))


def _find_link(item_text: str, definitions: dict):
    """First link in a list item: an inline link or autolink if there is one, otherwise a
    reference whose definition exists. Returns (title, url) or None."""
    masked = _mask_code(item_text)
    constructs = _scan_links(masked)
    best = None
    for kind, start, _end, t0, t1, dest in constructs:
        if kind != "link":
            continue
        url = re.sub(r"\\(.)", r"\1", dest).strip()
        if not url:
            continue  # "[text]()" is not a usable link
        best = (start, _plain(item_text[t0:t1]).strip() or url, url)
        break
    auto = AUTOLINK_RE.search(masked)
    if auto and (best is None or auto.start() < best[0]):
        best = (auto.start(), auto.group(1), auto.group(1))
    if best is not None:
        return best[1], best[2]
    for kind, _start, _end, t0, t1, label in constructs:
        if kind == "ref" and _label(label) in definitions:
            return _plain(item_text[t0:t1]).strip() or _label(label), definitions[_label(label)]
    return None


def parse_llms_txt(raw: str) -> dict:
    """Extract the structural facts the proposal talks about. Only top-level blocks
    count (a heading inside a code fence, a quote or a list item is not a heading)."""
    text = raw[1:] if raw.startswith("﻿") else raw
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = len(lines)

    doc = {
        "h1": None, "h1_count": 0, "extra_h1_lines": [],
        "summary": None, "summary_line": None,
        "sections": [], "entries": [], "non_link_items": [],
        "max_heading_depth": 0, "deepest_heading_line": None,
    }

    # Pass 1: reference definitions (outside fenced code). A definition cannot interrupt a
    # paragraph: "[x]: url" right under a line of text is just more text, not a definition.
    definitions = {}
    def_lines = set()
    fence = None
    text_open = False
    html_until = 0
    for idx, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = None
            text_open = False
            continue
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = m.group(1)
            text_open = False
            continue
        if not line.strip():
            text_open = False
            continue
        if idx < html_until:
            continue  # inside an HTML block: nothing here is Markdown
        end = _html_block_end(lines, idx, text_open)
        if end is not None:
            html_until = end
            text_open = False
            continue
        d = DEF_RE.match(re.sub(r"^(?: {0,3}>[ \t]?)+", "", line))
        if d and not text_open:
            definitions.setdefault(_label(d.group(1)), d.group(2))
            def_lines.add(idx)
            continue  # text_open stays False: definitions may follow one another
        it = ITEM_RE.match(line)
        quoted = QUOTE_RE.match(line)
        if _atx(line) or BREAK_RE.match(line) or (it and not (it.group(4) or "").strip()) or (quoted and not quoted.group(1).strip()):
            text_open = False  # headings, rules, empty list items and empty quote lines leave no paragraph open
        else:
            text_open = True

    def heading(depth: int, title: str, line_no: int) -> None:
        if depth > doc["max_heading_depth"]:
            doc["max_heading_depth"] = depth
            doc["deepest_heading_line"] = line_no
        if depth == 1:
            doc["h1_count"] += 1
            if doc["h1"] is None:
                doc["h1"] = {"text": title, "line": line_no}
            else:
                doc["extra_h1_lines"].append(line_no)
        elif depth == 2:
            doc["sections"].append({"title": title, "line": line_no})

    entries = {}
    i = 0
    paragraph_open = False  # a paragraph-like run is open: constructs that "cannot interrupt a paragraph" stay text
    para_text = False       # ...and it already holds a line of real text (a setext underline needs one)
    code_adjacent = False   # the previous line closed an indented code block with no blank line in between
    while i < n:
        line = lines[i]
        if not line.strip():
            paragraph_open = para_text = code_adjacent = False
            i += 1
            continue
        after_code, code_adjacent = code_adjacent, False

        m = FENCE_RE.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            mark = m.group(1)
            i += 1
            while i < n:
                c = FENCE_RE.match(lines[i])
                if c and c.group(1)[0] == mark[0] and len(c.group(1)) >= len(mark) and not c.group(2).strip():
                    break
                i += 1
            i += 1
            paragraph_open = False
            continue

        if paragraph_open and para_text:
            s = SETEXT_RE.match(line)
            if s:  # underline of the paragraph just read -> setext heading
                heading(1 if s.group(1)[0] == "=" else 2, _plain(lines[i - 1]).strip(), i)
                paragraph_open = para_text = False
                i += 1
                continue

        if not paragraph_open and INDENTED_RE.match(line):
            while i < n and (INDENTED_RE.match(lines[i]) or not lines[i].strip()):
                i += 1
            # Trailing blank lines are not part of the block; note whether text follows directly.
            code_adjacent = i < n and bool(lines[i - 1].strip())
            continue  # indented code block

        m = _atx(line)
        if m:
            heading(m.depth, _plain(m.title).strip(), i + 1)
            paragraph_open = False
            i += 1
            continue

        if BREAK_RE.match(line):
            paragraph_open = False
            i += 1
            continue

        m = QUOTE_RE.match(line)
        if m:
            start = i
            parts = []
            quote_para = False  # a paragraph is open inside the quote (only then may a bare line continue it)
            while i < n and lines[i].strip():
                q = QUOTE_RE.match(lines[i])
                if q:
                    inner = q.group(1)
                    parts.append(inner)
                    quote_para = bool(inner.strip()) and not (_atx(inner) or FENCE_RE.match(inner) or BREAK_RE.match(inner) or ITEM_RE.match(inner))
                elif not quote_para or _atx(lines[i]) or ITEM_RE.match(lines[i]) or FENCE_RE.match(lines[i]) or BREAK_RE.match(lines[i]) or _html_block_end(lines, i, True) is not None:
                    break
                else:
                    parts.append(lines[i])  # lazy continuation of the quoted paragraph
                i += 1
            if doc["summary"] is None:
                doc["summary"] = _plain("\n".join(parts)).strip()
                doc["summary_line"] = start + 1
            paragraph_open = para_text = False
            continue

        m = ITEM_RE.match(line)
        # An empty item, or an ordered item not numbered 1, cannot interrupt a paragraph (nor follow
        # an indented code block without a blank line): it stays plain text.
        if m and not ((paragraph_open or after_code) and (m.group(4) is None or not m.group(4).strip() or (m.group(2)[0].isdigit() and m.group(2)[:-1] != "1"))):
            # A list: collect top-level items until the list ends.
            while i < n:
                it = ITEM_RE.match(lines[i])
                if not it:
                    break
                item_line = i + 1
                body = [it.group(4) or ""]
                empty_start = not (it.group(4) or "").strip()  # nothing after the marker: no paragraph to continue lazily
                # Content offset of this item: a later marker indented at least this far is nested inside it.
                gap = it.group(3) or " "
                width = len(it.group(1)) + len(it.group(2)) + (4 - (len(it.group(1)) + len(it.group(2))) % 4 if gap[0] == "\t" else min(len(gap), 4) if len(gap) <= 4 else 1)
                i += 1
                while i < n:
                    cur = lines[i]
                    if not cur.strip() and empty_start and len(body) == 1:
                        # An item may begin with at most one blank line: marker, blank -> the item is empty
                        # and whatever follows (even if indented) is not part of it.
                        while i < n and not lines[i].strip():
                            i += 1
                        break
                    if not cur.strip():
                        j = i
                        while j < n and not lines[j].strip():
                            j += 1
                        if j < n and (lines[j].startswith("\t") or len(lines[j]) - len(lines[j].lstrip(" ")) >= width):
                            i = j
                            continue  # blank line(s) inside the item
                        i = j
                        break
                    indent = len(cur) - len(cur.lstrip(" "))
                    sibling = ITEM_RE.match(cur) and indent < width
                    if sibling or ((_atx(cur) or BREAK_RE.match(cur) or FENCE_RE.match(cur)) and indent < width):
                        break
                    if QUOTE_RE.match(cur) and indent < width:
                        break
                    if indent < width and (HTML_BLOCK_RE.match(cur) or HTML_COMMENT_RE.match(cur) or HTML_RAW_RE.match(cur)):
                        break
                    if i in def_lines:
                        break  # a real definition is not part of the item
                    if empty_start and indent < width and len(body) == 1:
                        break  # an empty item has no paragraph that an unindented line could continue
                    body.append(re.sub(r"^\s*(?:[-*+]|\d{1,9}[.)])[ \t]+", "", cur) if cur.startswith(" ") or cur.startswith("\t") else cur)
                    i += 1
                item_text = "\n".join(body)
                found = _find_link(item_text, definitions)
                if found is None:
                    doc["non_link_items"].append(item_line)
                else:
                    title, raw_url = found
                    norm = normalize_url(raw_url)
                    url = norm if norm is not None else raw_url
                    if url in entries:
                        entries[url]["occurrences"] += 1
                    else:
                        rest = LEADING_SEP_RE.sub("", _plain(item_text, definitions).strip().replace(title, "", 1)).strip()
                        entries[url] = {
                            "url": url, "raw_url": raw_url, "title": title,
                            "section": doc["sections"][-1]["title"] if doc["sections"] else None,
                            "description": rest or None, "line": item_line, "occurrences": 1,
                        }
                if i < n and not ITEM_RE.match(lines[i]):
                    break
                if i >= n:
                    break
                if i > 0 and not lines[i - 1].strip() and not ITEM_RE.match(lines[i]):
                    break
            paragraph_open = False
            continue

        html_end = _html_block_end(lines, i, paragraph_open)
        if html_end is not None:
            i = html_end
            paragraph_open = False
            continue

        if i in def_lines:
            # A definition is carved out of a paragraph-like run: what follows still obeys the
            # "cannot interrupt a paragraph" rules (setext underline, ordered list not starting at 1).
            paragraph_open, para_text = True, False
            i += 1
            continue

        paragraph_open = para_text = True
        i += 1

    doc["entries"] = list(entries.values())
    return doc


# ============================================================================
# Part 2. Rules
# ============================================================================

def validate_spec(doc: dict) -> dict:
    """Only what the proposal says. Verdict: FAIL if any CRITICAL/MAJOR, WARN if any
    other issue, else PASS."""
    issues = []

    def add(code, severity, message, line=None):
        issues.append({"code": code, "severity": severity, "message": message, "line": line})

    if doc["h1_count"] == 0:
        add("SPEC_H1_MISSING", "CRITICAL", "No H1 title. The proposal requires exactly one H1 carrying the project name.")
    elif doc["h1_count"] > 1:
        add("SPEC_H1_MULTIPLE", "MAJOR", "%d H1 titles found; the proposal defines exactly one." % doc["h1_count"],
            doc["extra_h1_lines"][0] if doc["extra_h1_lines"] else None)
    if doc["summary"] is not None and doc["summary"] == "":
        add("SPEC_SUMMARY_EMPTY", "MINOR", "The summary blockquote is empty.", doc["summary_line"])
    if doc["max_heading_depth"] > 2:
        add("SPEC_SECTION_DEPTH", "MINOR", "Headings deeper than H2 are present; sections should be H2.", doc["deepest_heading_line"])
    total = len(doc["non_link_items"])
    for line in doc["non_link_items"]:
        add("SPEC_ENTRY_NOT_LINK", "MINOR",
            "List item has no link (entry format is `- [name](url): description`); %d such item(s) in the file." % total, line)

    if any(i["severity"] in ("CRITICAL", "MAJOR") for i in issues):
        verdict = "FAIL"
    elif issues:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "issues": issues}


def build_advice(doc: dict) -> list:
    """Editorial suggestions. None of these are proposal requirements."""
    out = []

    def add(code, message, line=None):
        out.append({"code": code, "message": message, "line": line, "nonStandard": True})

    if doc["summary"] is None:
        add("ADVICE_SUMMARY_MISSING", "No summary blockquote. A one-sentence summary helps a reader decide whether the docs are relevant.")
    if not doc["sections"] and doc["entries"]:
        add("ADVICE_NO_SECTIONS", "Entries are not grouped under H2 sections.")
    no_desc = [e for e in doc["entries"] if not e["description"]]
    if no_desc:
        add("ADVICE_ENTRY_NO_DESCRIPTION", "%d entr%s without a description." % (len(no_desc), "y" if len(no_desc) == 1 else "ies"), no_desc[0]["line"])
    relative = [e for e in doc["entries"] if e["url"] == e["raw_url"] and not HTTP_RE.match(e["raw_url"])]
    if relative:
        add("ADVICE_RELATIVE_URL", "%d entr%s not written as an absolute http(s) URL." % (len(relative), "y" if len(relative) == 1 else "ies"), relative[0]["line"])
    return out


def summarize(text: str) -> dict:
    """Parse + rules in one call. This is what the fixtures pin down."""
    doc = parse_llms_txt(text)
    spec = validate_spec(doc)
    return {
        "spec": spec,
        "advice": {"items": build_advice(doc)},
        "metrics": {
            "bytes": len(text.encode("utf-8")),
            "sections": len(doc["sections"]),
            "entries": len(doc["entries"]),
            "h1": doc["h1"]["text"] if doc["h1"] else None,
        },
        "_doc": doc,
    }


def code_counts(result: dict) -> dict:
    """Stable projection used by the shared fixtures (and by the web checker's parity test)."""
    spec_counts = {}
    for i in result["spec"]["issues"]:
        key = i["code"] + "/" + i["severity"]
        spec_counts[key] = spec_counts.get(key, 0) + 1
    advice_counts = {}
    for a in result["advice"]["items"]:
        advice_counts[a["code"]] = advice_counts.get(a["code"], 0) + 1
    return {
        "verdict": result["spec"]["verdict"],
        "spec": dict(sorted(spec_counts.items())),
        "advice": dict(sorted(advice_counts.items())),
        "adviceNonStandard": all(a.get("nonStandard") is True for a in result["advice"]["items"]),
    }


# ============================================================================
# Part 3. Network (child process + parent-enforced deadline)
# ============================================================================

class FetchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_public_ip(addr: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            ip = mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_private:
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT:
        return False
    return bool(ip.is_global)


def check_url_shape(url: str):
    """Scheme and credential rules that apply to every hop."""
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        raise FetchError("INVALID_URL", "not a valid URL")
    if p.scheme.lower() not in ("http", "https"):
        raise FetchError("SAFE_BLOCKED_SCHEME", "only http and https are fetched")
    if p.username is not None or p.password is not None:
        raise FetchError("SAFE_BLOCKED_CREDENTIALS", "URLs carrying credentials are not fetched")
    if not p.hostname:
        raise FetchError("INVALID_URL", "URL has no host")
    return p, port


def default_resolver(host: str, port: int) -> list:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError("DNS_ERROR", "could not resolve %s (%s)" % (host, e))
    addrs = []
    for info in infos:
        a = info[4][0]
        if a not in addrs:
            addrs.append(a)
    if not addrs:
        raise FetchError("DNS_ERROR", "no addresses for %s" % host)
    return addrs


def resolve_checked(host: str, port: int, allow_private: bool, resolver=default_resolver, public_check=is_public_ip) -> str:
    """Resolve, refuse if ANY returned address is not public, return the address to connect to.
    Connecting to this exact address (not re-resolving) closes the check/use DNS gap."""
    addrs = resolver(host, port)
    if not allow_private:
        for a in addrs:
            if not public_check(a):
                raise FetchError("SAFE_BLOCKED_PRIVATE", "%s resolves to a non-public address; use --allow-private to check internal hosts" % host)
    return addrs[0]


class _PinnedHTTP(HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        # Certificate and SNI use the original host name, not the pinned address.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_follow(url: str, max_bytes: int, allow_private: bool, timeout: float,
                 resolver=default_resolver, public_check=is_public_ip, max_redirects: int = MAX_REDIRECTS,
                 max_requests: int = MAX_REDIRECTS + 1, counter=None) -> dict:
    """One logical request: manual redirects, every hop re-validated. No environment proxy.
    Every hop is one HTTP request and counts against max_requests; `counter` (a one-item list)
    reports how many were actually sent, also when the fetch fails."""
    chain = []
    current = url
    counter = counter if counter is not None else [0]
    for _ in range(max_redirects + 1):
        if counter[0] >= max_requests:
            raise FetchError("BUDGET_EXCEEDED", "request budget used up while following redirects")
        p, port = check_url_shape(current)
        https = p.scheme.lower() == "https"
        port = port or (443 if https else 80)
        ip = resolve_checked(p.hostname, port, allow_private, resolver, public_check)
        conn = (_PinnedHTTPS if https else _PinnedHTTP)(p.hostname, port, ip, timeout)
        try:
            target = (p.path or "/") + ("?" + p.query if p.query else "")
            counter[0] += 1
            try:
                conn.request("GET", target, headers={
                    "User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain, */*;q=0.1",
                    "Accept-Encoding": "identity", "Connection": "close",
                })
                resp = conn.getresponse()
            except ssl.SSLError as e:
                raise FetchError("TLS_ERROR", "TLS failure: %s" % e)
            except socket.timeout:
                raise FetchError("TIMEOUT", "request timed out")
            except OSError as e:
                raise FetchError("NETWORK_ERROR", "connection failed: %s" % e)
            status = resp.status
            location = resp.getheader("Location")
            if status in (301, 302, 303, 307, 308) and location:
                chain.append(current)
                current = urljoin(current, location)
                continue
            encoding = (resp.getheader("Content-Encoding") or "identity").strip().lower()
            if encoding not in ("", "identity"):
                raise FetchError("ENCODED_RESPONSE", "server sent Content-Encoding %s although identity was requested; not decoding" % encoding)
            try:
                body = resp.read(max_bytes + 1)
            except socket.timeout:
                raise FetchError("TIMEOUT", "response body timed out")
            except OSError as e:
                raise FetchError("NETWORK_ERROR", "read failed: %s" % e)
            truncated = len(body) > max_bytes
            return {
                "ok": True, "status": status, "finalUrl": current, "redirects": chain, "requests": counter[0],
                "contentType": resp.getheader("Content-Type") or "",
                "truncated": truncated, "body": body[:max_bytes].decode("utf-8", errors="replace"),
            }
        finally:
            conn.close()
    raise FetchError("TOO_MANY_REDIRECTS", "more than %d redirects" % max_redirects)


def fetch_via_env_proxy(url: str, max_bytes: int, timeout: float, max_requests: int = MAX_REDIRECTS + 1, counter=None) -> dict:
    """Opt-in path for networks that only work through a proxy. Address checks cannot be
    done locally here - the proxy decides what it connects to."""
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    chain = []
    current = url
    counter = counter if counter is not None else [0]
    for _ in range(MAX_REDIRECTS + 1):
        if counter[0] >= max_requests:
            raise FetchError("BUDGET_EXCEEDED", "request budget used up while following redirects")
        check_url_shape(current)
        counter[0] += 1
        req = urllib.request.Request(current, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:  # noqa: BLE001 - surfaced as a network failure
            raise FetchError("NETWORK_ERROR", "request via proxy failed: %s" % e)
        status = resp.getcode()
        location = resp.headers.get("Location")
        if status in (301, 302, 303, 307, 308) and location:
            chain.append(current)
            current = urljoin(current, location)
            continue
        if (resp.headers.get("Content-Encoding") or "identity").strip().lower() not in ("", "identity"):
            raise FetchError("ENCODED_RESPONSE", "encoded response; not decoding")
        body = resp.read(max_bytes + 1)
        return {"ok": True, "status": status, "finalUrl": current, "redirects": chain, "requests": counter[0],
                "contentType": resp.headers.get("Content-Type") or "",
                "truncated": len(body) > max_bytes, "body": body[:max_bytes].decode("utf-8", errors="replace")}
    raise FetchError("TOO_MANY_REDIRECTS", "more than %d redirects" % MAX_REDIRECTS)


WORKER_STDIN_LIMIT = 65536


def _bounded_int(value, low: int, high: int, default: int) -> int:
    """Clamp an untrusted number into [low, high]; anything that is not a finite number -> default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return default
    return max(low, min(high, int(value)))


def worker_main() -> int:
    """Child process. Reads one small JSON job on stdin (whitelisted fields only, every number
    clamped), writes one JSON result on stdout. Never spawns anything. It is meant to be started
    by fetch() below, which enforces the deadline; started by hand it still applies all address
    rules and size limits, with the socket timeout as its only time limit."""
    counter = [0]
    try:
        raw = sys.stdin.buffer.read(WORKER_STDIN_LIMIT + 1)  # bytes, so the limit is a real byte limit
        if len(raw) > WORKER_STDIN_LIMIT:
            raise FetchError("INVALID_URL", "job too large")
        job = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(job, dict):
            raise FetchError("INVALID_URL", "malformed job")
        url = job.get("url")
        if not isinstance(url, str) or len(url) > 8192:
            raise FetchError("INVALID_URL", "missing or oversized url")
        max_bytes = _bounded_int(job.get("max_bytes"), 1, MAX_BODY_BYTES, MAX_BODY_BYTES)
        max_requests = _bounded_int(job.get("max_requests"), 1, MAX_REDIRECTS + 1, MAX_REDIRECTS + 1)
        t = job.get("timeout")
        timeout = float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t <= REQUEST_DEADLINE_S else REQUEST_DEADLINE_S
        if job.get("use_env_proxy") is True:
            result = fetch_via_env_proxy(url, max_bytes, timeout, max_requests=max_requests, counter=counter)
        else:
            result = fetch_follow(url, max_bytes, job.get("allow_private") is True, timeout, max_requests=max_requests, counter=counter)
    except FetchError as e:
        result = {"ok": False, "error": e.code, "message": str(e), "requests": counter[0]}
    except Exception as e:  # noqa: BLE001 - the parent only needs a failure record
        result = {"ok": False, "error": "NETWORK_ERROR", "message": "%s: %s" % (type(e).__name__, e), "requests": counter[0]}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


class Budget:
    """Global deadline and request count shared by every fetch of one run."""

    def __init__(self, seconds: float = GLOBAL_DEADLINE_S, requests: int = MAX_REQUESTS):
        self.deadline = time.monotonic() + seconds
        self.requests_left = requests

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


def fetch(url: str, budget: Budget, max_bytes: int = MAX_BODY_BYTES, allow_private: bool = False,
          use_env_proxy: bool = False, request_deadline: float = REQUEST_DEADLINE_S) -> dict:
    """Run one fetch in a child process and enforce the deadline from here."""
    if budget.requests_left <= 0:
        return {"ok": False, "error": "BUDGET_EXCEEDED", "message": "request budget used up"}
    limit = min(request_deadline, budget.remaining())
    if limit <= 0:
        return {"ok": False, "error": "TIMEOUT", "message": "overall time limit reached"}
    # Redirect hops are requests too: the worker may send at most `allowed` and reports how many it sent.
    allowed = min(budget.requests_left, MAX_REDIRECTS + 1)
    job = json.dumps({"url": url, "max_bytes": max_bytes, "allow_private": bool(allow_private),
                      "use_env_proxy": bool(use_env_proxy), "timeout": limit, "max_requests": allowed})
    # Fixed argv, no shell, the URL travels as data on stdin.
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), WORKER_FLAG],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    cap = max_bytes * 6 + 65536  # JSON escaping can expand a byte up to 6x
    chunks = []
    state = {"size": 0, "overflow": False}

    def pump():
        try:
            while True:
                data = proc.stdout.read(65536)
                if not data:
                    return
                state["size"] += len(data)
                if state["size"] > cap:
                    state["overflow"] = True
                    proc.kill()
                    return
                chunks.append(data)
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    try:
        try:
            proc.stdin.write(job.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=5)
        for pipe in (proc.stdin, proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass
    result = None
    if timed_out:
        result = {"ok": False, "error": "TIMEOUT", "message": "no complete response within %.0fs" % limit}
    elif state["overflow"]:
        result = {"ok": False, "error": "TOO_LARGE", "message": "response larger than the read limit"}
    else:
        try:
            result = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            result = None
        if not isinstance(result, dict):
            result = {"ok": False, "error": "NETWORK_ERROR", "message": "fetch worker produced no usable result"}
    # Charge what was really sent; when the worker could not report it (killed, garbled), assume the worst.
    sent = result.get("requests")
    budget.requests_left -= sent if isinstance(sent, int) and not isinstance(sent, bool) and 0 <= sent <= allowed else allowed
    return result


# ============================================================================
# Part 4. Lightweight usability observations (URL input only)
# ============================================================================

HTML_HEAD_RE = re.compile(r"^\s*(?:<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>])", re.I)
MD_SIGNAL_RE = re.compile(r"(?m)^(?:#{1,6}[ \t]|[ \t]{0,8}[-*+][ \t]{1,4}\[|>[ \t])")


def usable_checks(res: dict) -> dict:
    """A small subset of what the web checker observes. These are not proposal rules."""
    checks = []

    def add(code, verdict, message):
        checks.append({"code": code, "verdict": verdict, "message": message})

    if not res.get("ok"):
        add("HTTP_STATUS", "FAIL", "%s: %s" % (res.get("error"), res.get("message")))
        return {"verdict": "FAIL", "checks": checks, "errorCode": res.get("error")}
    status = res["status"]
    hops = len(res.get("redirects") or [])
    add("HTTP_STATUS", "FAIL" if status >= 400 else "PASS", "HTTP %d%s" % (status, " after %d redirect(s)" % hops if hops else ""))
    if status >= 400:
        return {"verdict": "FAIL", "checks": checks}
    body = res.get("body") or ""
    ctype = (res.get("contentType") or "").lower()
    looks_html = bool(HTML_HEAD_RE.match(body[:2048]))
    html_page = looks_html and not MD_SIGNAL_RE.search(body[:20000])
    if html_page:
        add("CONTENT_TYPE", "FAIL" if "html" in ctype else "WARN", ctype or "no Content-Type header")
        add("SPA_DETECTED", "FAIL", "The response is an HTML page, not a Markdown file (often an SPA fallback route swallowing /llms.txt).")
    elif "html" in ctype:
        add("CONTENT_TYPE", "WARN", "%s - the body looks like Markdown but is served as HTML" % ctype)
    elif not ctype:
        add("CONTENT_TYPE", "UNKNOWN", "no Content-Type header")
    else:
        add("CONTENT_TYPE", "PASS" if re.search(r"markdown|text|octet-stream", ctype) else "UNKNOWN", ctype)
    size = len(body.encode("utf-8"))
    if size == 0:
        add("FILE_SIZE", "WARN", "empty file")
    elif res.get("truncated"):
        add("FILE_SIZE", "WARN", "larger than %d bytes; only the first part was read, so the structure result is incomplete" % MAX_BODY_BYTES)
    else:
        add("FILE_SIZE", "PASS", "%d bytes" % size)
    verdicts = [c["verdict"] for c in checks]
    verdict = "FAIL" if "FAIL" in verdicts else "WARN" if "WARN" in verdicts else "PASS"
    return {"verdict": verdict, "checks": checks}


def check_links(doc: dict, base_url, budget: Budget, max_links: int, allow_private: bool, use_env_proxy: bool) -> dict:
    """Sample entry links. A timeout or a refusal is 'not confirmed', never 'dead'."""
    targets = []
    for e in doc["entries"]:
        raw = e["raw_url"]
        url = raw if HTTP_RE.match(raw) else (urljoin(base_url, raw) if base_url else None)
        if url and HTTP_RE.match(url) and url not in targets:
            targets.append(url)
    sample = targets[:max_links]
    dead, unconfirmed, ok = [], [], 0
    for url in sample:
        r = fetch(url, budget, max_bytes=LINK_BODY_BYTES, allow_private=allow_private, use_env_proxy=use_env_proxy)
        if r.get("ok"):
            if r["status"] >= 400 and r["status"] not in (401, 403, 429):
                dead.append({"url": url, "reason": "HTTP %d" % r["status"]})
            elif r["status"] >= 400:
                unconfirmed.append({"url": url, "reason": "HTTP %d (access refused or rate limited)" % r["status"]})
            else:
                ok += 1
        elif r.get("error") == "DNS_ERROR":
            dead.append({"url": url, "reason": r.get("message")})
        else:
            unconfirmed.append({"url": url, "reason": "%s: %s" % (r.get("error"), r.get("message"))})
    verdict = "FAIL" if dead else "WARN" if unconfirmed else "PASS"
    return {"code": "LINK_HEALTH", "verdict": verdict,
            "coverage": {"total": len(targets), "sampled": len(sample), "completed": ok + len(dead) + len(unconfirmed)},
            "reachable": ok, "dead": dead, "unconfirmed": unconfirmed}


# ============================================================================
# Part 5. CLI
# ============================================================================

def render_text(report: dict) -> str:
    out = []
    out.append("llms.txt check: %s" % report["target"])
    usable = report.get("usable")
    if usable:
        out.append("")
        out.append("Usability (observed, not proposal rules): %s" % usable["verdict"])
        for c in usable["checks"]:
            out.append("  [%s] %s - %s" % (c["verdict"], c["code"], c["message"]))
        links = usable.get("links")
        if links:
            cov = links["coverage"]
            out.append("  [%s] LINK_HEALTH - %d of %d links sampled, %d reachable, %d dead, %d not confirmed"
                       % (links["verdict"], cov["sampled"], cov["total"], links["reachable"], len(links["dead"]), len(links["unconfirmed"])))
            for d in links["dead"]:
                out.append("        dead: %s (%s)" % (d["url"], d["reason"]))
            for u in links["unconfirmed"][:5]:
                out.append("        not confirmed: %s (%s)" % (u["url"], u["reason"]))
    spec = report.get("spec")
    if spec:
        out.append("")
        out.append("Spec (llmstxt.org proposal): %s" % spec["verdict"])
        groups = {}
        for i in spec["issues"]:
            groups.setdefault((i["code"], i["severity"], i["message"]), []).append(i["line"])
        for (code, sev, msg), lines in groups.items():
            where = [str(x) for x in lines if x is not None]
            shown = ", ".join(where[:8]) + (" ... (+%d more)" % (len(where) - 8) if len(where) > 8 else "")
            out.append("  [%s] %s x%d - %s%s" % (sev, code, len(lines), msg, " | line " + shown if shown else ""))
        if not spec["issues"]:
            out.append("  no issues")
        advice = report["advice"]["items"]
        out.append("")
        out.append("Advice (editorial, not part of the proposal): %d" % len(advice))
        for a in advice:
            out.append("  %s - %s%s" % (a["code"], a["message"], " | first at line %d" % a["line"] if a["line"] else ""))
        m = report["metrics"]
        out.append("")
        out.append("Metrics: %d bytes, %d section(s), %d entr%s" % (m["bytes"], m["sections"], m["entries"], "y" if m["entries"] == 1 else "ies"))
    else:
        out.append("")
        out.append("Spec: not checked (the file could not be read as Markdown)")
    out.append("")
    out.append("Codes are explained in references/error-codes.md. The online checker is authoritative for deployed files.")
    return "\n".join(out)


def run(argv) -> int:
    ap = argparse.ArgumentParser(prog="validate_llms_txt.py", description="Validate an llms.txt file (llmstxt.org proposal).")
    ap.add_argument("target", help="path to a local file, or an http(s) URL")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--check-links", action="store_true", help="also sample entry links (off by default)")
    ap.add_argument("--max-links", type=int, default=MAX_LINKS_DEFAULT, help="links to sample with --check-links (default %d, max %d)" % (MAX_LINKS_DEFAULT, MAX_LINKS_DEFAULT))
    ap.add_argument("--allow-private", action="store_true", help="allow non-public addresses (local or internal hosts)")
    ap.add_argument("--use-env-proxy", action="store_true", help="send requests through the proxy from environment variables (local address checks no longer apply)")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args(argv)
    max_links = max(0, min(args.max_links, MAX_LINKS_DEFAULT))
    budget = Budget()
    report = {"target": args.target, "validatorVersion": VERSION}
    base_url = None
    text = None

    if HTTP_RE.match(args.target):
        res = fetch(args.target, budget, allow_private=args.allow_private, use_env_proxy=args.use_env_proxy)
        report["usable"] = usable_checks(res)
        if res.get("ok") and res["status"] < 400:
            base_url = res["finalUrl"]
            html = any(c["code"] == "SPA_DETECTED" for c in report["usable"]["checks"])
            if not html:
                text = res["body"]
    elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", args.target):
        sys.stderr.write("error: only http(s) URLs or local paths are accepted\n")
        return 2
    else:
        try:
            with open(args.target, "rb") as f:
                text = f.read().decode("utf-8", errors="replace")
        except OSError as e:
            sys.stderr.write("error: cannot read %s: %s\n" % (args.target, e))
            return 2

    if text is not None:
        result = summarize(text)
        doc = result.pop("_doc")
        report.update(result)
        if args.check_links:
            links = check_links(doc, base_url, budget, max_links, args.allow_private, args.use_env_proxy)
            report.setdefault("usable", {"verdict": "PASS", "checks": []})
            report["usable"]["links"] = links
            order = ["PASS", "WARN", "FAIL"]
            if order.index(links["verdict"]) > order.index(report["usable"]["verdict"]):
                report["usable"]["verdict"] = links["verdict"]

    sys.stdout.write((json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report)) + "\n")
    failed = (report.get("spec", {}).get("verdict") == "FAIL") or (report.get("usable", {}).get("verdict") == "FAIL")
    return 1 if failed else 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == WORKER_FLAG:
        return worker_main()
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
