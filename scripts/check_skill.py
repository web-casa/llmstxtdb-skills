#!/usr/bin/env python3
"""Repository checks that do not need the network: skill front matter, references that
SKILL.md points to, plugin manifests, and no leftovers that should not be published."""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "llms-txt")
errors = []


def check(cond: bool, message: str) -> None:
    if not cond:
        errors.append(message)


with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
    skill = f.read()
m = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
check(m is not None, "SKILL.md: missing YAML front matter")
front = m.group(1) if m else ""
name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
desc = re.search(r"^description:\s*(.+)$", front, re.M)
check(bool(name) and name.group(1) == "llms-txt", "SKILL.md: name must be llms-txt (and match the directory)")
check(bool(name) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name.group(1)) is not None, "SKILL.md: name must be lowercase words joined by hyphens")
check(bool(desc) and 40 <= len(desc.group(1)) <= 1024, "SKILL.md: description must be 40-1024 characters")
check(len(skill.splitlines()) <= 500, "SKILL.md: keep it under 500 lines; move detail into references/")

for ref in sorted(set(re.findall(r"`((?:references|scripts)/[\w./-]+)`", skill))):
    check(os.path.exists(os.path.join(SKILL, ref)), "SKILL.md points to a missing file: %s" % ref)

with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
    plugin = json.load(f)
with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
    market = json.load(f)
check(plugin.get("license") == "MIT", "plugin.json: license")
check(re.fullmatch(r"\d+\.\d+\.\d+", plugin.get("version", "")) is not None, "plugin.json: version must be x.y.z")
version = re.search(r'^\s*version:\s*"?([\d.]+)"?\s*$', front, re.M)
check(bool(version) and version.group(1) == plugin.get("version"), "SKILL.md metadata.version and plugin.json version differ")
with open(os.path.join(SKILL, "scripts", "validate_llms_txt.py"), encoding="utf-8") as f:
    script_version = re.search(r'^VERSION = "([\d.]+)"', f.read(), re.M)
check(bool(script_version) and script_version.group(1) == plugin.get("version"), "validator VERSION and plugin.json version differ")
names = [p.get("name") for p in market.get("plugins", [])]
check(names == [plugin.get("name")], "marketplace.json must list exactly the plugin from plugin.json")
for p in market.get("plugins", []):
    check(os.path.isdir(os.path.join(ROOT, p.get("source", "missing"))), "marketplace.json: plugin source path does not exist")

# Nothing that should stay private, no placeholder domains, no symlinks.
FORBIDDEN = re.compile(r"llmstxtdb\.example|/home/|/Users/|ADMIN_PASSWORD|DATABASE_URL|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}")
for base, dirs, files in os.walk(ROOT):
    for d in dirs:
        check(not os.path.islink(os.path.join(base, d)), "symlinked directory is not allowed: %s" % os.path.relpath(os.path.join(base, d), ROOT))
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules") and not os.path.islink(os.path.join(base, d))]
    for fn in files:
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, ROOT)
        check(not os.path.islink(path), "symlink is not allowed: %s" % rel)
        check(not fn.startswith(".env"), "environment file must not be published: %s" % rel)
        if rel == os.path.join("scripts", "check_skill.py"):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        hit = FORBIDDEN.search(text)
        check(hit is None, "%s contains something that should not be published: %r" % (rel, hit.group(0) if hit else ""))

if errors:
    print("\n".join("FAIL " + e for e in errors))
    sys.exit(1)
print("skill checks passed")
