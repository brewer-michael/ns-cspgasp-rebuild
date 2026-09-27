#!/usr/bin/env python3
"""Check that docs/shopping-list.html and docs/BOM.md agree.

Both list the same parts: every store link in BOM.md must be on the page, every
part on the page must have its main link, price and estimate mark in a BOM.md
table, and the totals in BOM.md's summary must match the page's data.
"""

import json
import math
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
DATA = re.compile(r'<script type="application/json" id="bom-data">(.*?)</script>', re.DOTALL)
SUMMARY_ROW = re.compile(r"\| \[[^\]]+\]\(#([a-z0-9-]+)\)[^|]*\|([^|]*)\|([^|]*)\|")


def load_page() -> dict:
    block = DATA.search((DOCS / "shopping-list.html").read_text(encoding="utf-8"))
    if block is None:
        sys.exit("shopping-list.html: no bom-data block")
    return json.loads(block.group(1))


def money(cell: str) -> float | None:
    found = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", cell)
    return float(found.group(1)) if found else None


def main() -> int:
    data = load_page()
    md = (DOCS / "BOM.md").read_text(encoding="utf-8")
    groups = {g["id"]: g for g in data["groups"]}
    items = data["items"]
    errors = []

    page_links = {it["url"] for it in items}
    page_links |= {a["url"] for it in items for a in it.get("also", [])}
    for url in LINK.findall(md):
        if url not in page_links:
            errors.append(f"BOM.md links {url}, but the page doesn't")

    # the table row that holds each link: | Part | Qty | Buy | Price | ...
    rows = {}
    for line in md.splitlines():
        if line.startswith("| "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            for url in LINK.findall(line):
                rows[url] = cells
    for it in items:
        cells = rows.get(it["url"])
        if cells is None or len(cells) < 4:
            errors.append(f"{it['id']}: {it['url']} is not in a BOM.md table")
            continue
        if money(cells[3]) != it["price"]:
            errors.append(f"{it['id']}: price {it['price']} on the page, {cells[3]!r} in BOM.md")
        if ("≈" in cells[3]) != it["estimate"]:
            errors.append(f"{it['id']}: estimate mark differs ({cells[3]!r} in BOM.md)")

    # totals for one speaker, computed the way the page computes them
    def once(it):
        return bool(groups[it["group"]].get("once"))

    def per_speaker(it):
        used, pack = it["use"]
        return 0 if once(it) else round(it["price"] * used / pack, 2)

    def first_build(it):
        used, pack = it["use"]
        units = 1 if once(it) else math.ceil(used / pack - 1e-9)
        return round(units * it["price"], 2)

    summary = {}
    for line in md.splitlines():
        found = SUMMARY_ROW.match(line)
        if found:
            summary[found.group(1)] = (money(found.group(2)), money(found.group(3)))
    for gid, group in groups.items():
        if gid not in summary:
            errors.append(f"BOM.md's summary has no row for #{gid}")
            continue
        members = [it for it in items if it["group"] == gid]
        per = round(sum(per_speaker(it) for it in members), 2)
        first = round(sum(first_build(it) for it in members), 2)
        want_per, want_first = summary[gid]
        name = group["name"]
        if not group.get("once") and want_per != per:
            errors.append(f"{name}: {per:.2f} per speaker on the page, {want_per} in BOM.md")
        if want_first != first:
            errors.append(f"{name}: {first:.2f} first build on the page, {want_first} in BOM.md")

    # the speaker's totals for each brain, rounded to whole dollars in BOM.md
    for brain, label in (("esp32", "Speaker with the ESP32-S3"), ("pi", "Speaker with the Pi")):
        row = re.search(rf"\| \*\*{re.escape(label)}\*\* \|([^|]*)\|([^|]*)\|", md)
        if row is None:
            errors.append(f"BOM.md's summary has no '{label}' row")
            continue
        members = [
            it for it in items if not once(it) and groups[it["group"]].get("brain") in (None, brain)
        ]
        totals = (sum(per_speaker(it) for it in members), sum(first_build(it) for it in members))
        for cell, total in zip(row.groups(), totals, strict=True):
            if money(cell) is None or round(money(cell)) != round(total):
                errors.append(f"{label}: {total:.2f} on the page, {cell.strip()!r} in BOM.md")

    for error in errors:
        print(f"✖ {error}")
    if not errors:
        print(f"✔ shopping-list.html and BOM.md agree: {len(items)} parts, {len(page_links)} links")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
