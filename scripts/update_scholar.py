#!/usr/bin/env python3
"""Refresh the cached Google Scholar total using only the Python standard library."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Callable
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


PROFILE_ID = "slhAlQ0AAAAJ"
PROFILE_URL = f"https://scholar.google.com/citations?user={PROFILE_ID}&hl=en"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "assets/data/scholar.json"
MAX_HTML_BYTES = 2 * 1024 * 1024


class ScholarUpdateError(ValueError):
    """The response cannot be used as a verified Scholar citation total."""


@dataclass
class Cell:
    tag: str
    classes: set[str]
    text: str = ""


class ScholarTableParser(HTMLParser):
    """Read a complete, unambiguous statistics table, not publication counts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_count = 0
        self.table_open = False
        self.table_complete = False
        self.rows: list[list[Cell]] = []
        self.row: list[Cell] | None = None
        self.cell: Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id") or ""
        classes = set((attributes.get("class") or "").split())
        if "captcha" in element_id.lower() or any("captcha" in item.lower() for item in classes):
            raise ScholarUpdateError("Scholar returned a CAPTCHA challenge")
        if tag == "form" and "/sorry/" in (attributes.get("action") or ""):
            raise ScholarUpdateError("Scholar returned a traffic challenge")
        if tag == "table":
            if self.table_open:
                raise ScholarUpdateError("The Scholar statistics table contains a nested table")
            if element_id == "gsc_rsb_st":
                self.table_count += 1
                if self.table_count != 1:
                    raise ScholarUpdateError("The response contains multiple Scholar statistics tables")
                self.table_open = True
            return
        if not self.table_open:
            return
        if tag == "tr":
            if self.row is not None:
                raise ScholarUpdateError("The Scholar statistics table has an incomplete row")
            self.row = []
        elif tag in {"td", "th"}:
            if self.row is None or self.cell is not None:
                raise ScholarUpdateError("The Scholar statistics table has an incomplete cell")
            self.cell = Cell(tag, classes)

    def handle_endtag(self, tag: str) -> None:
        if not self.table_open:
            return
        if tag in {"td", "th"}:
            if self.cell is None or self.cell.tag != tag or self.row is None:
                raise ScholarUpdateError("The Scholar statistics table has mismatched cells")
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr":
            if self.row is None or self.cell is not None:
                raise ScholarUpdateError("The Scholar statistics table has an incomplete row")
            self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            if self.row is not None or self.cell is not None:
                raise ScholarUpdateError("The Scholar statistics table ended inside a row")
            self.table_open = False
            self.table_complete = True

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.text += data

    def total_citations(self) -> int:
        if not self.table_complete or self.table_open:
            raise ScholarUpdateError("A complete Scholar statistics table was not found")

        header_rows = [row for row in self.rows if any(cell.tag == "th" for cell in row)]
        if len(header_rows) != 1 or len(header_rows[0]) != 3:
            raise ScholarUpdateError("The Scholar statistics column headings are missing or ambiguous")
        if header_rows[0][1].text.strip() != "All":
            raise ScholarUpdateError("The first Scholar statistics column is not the All total")

        citation_rows = [
            row
            for row in self.rows
            if any(
                "gsc_rsb_sc1" in cell.classes and " ".join(cell.text.split()) == "Citations"
                for cell in row
            )
        ]
        if len(citation_rows) != 1:
            raise ScholarUpdateError("A unique Citations row was not found")
        row = citation_rows[0]
        if len(row) != 3 or "gsc_rsb_sc1" not in row[0].classes:
            raise ScholarUpdateError("The Scholar Citations row is incomplete")
        if any("gsc_rsb_std" not in cell.classes for cell in row[1:]):
            raise ScholarUpdateError("The Scholar Citations numeric cells are incomplete")

        value = row[1].text.strip()
        if re.fullmatch(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)", value) is None:
            raise ScholarUpdateError("The Scholar All citation total is not a nonnegative integer")
        return int(value.replace(",", ""))


def parse_total_citations(html: str) -> int:
    if "our systems have detected unusual traffic" in html.lower():
        raise ScholarUpdateError("Scholar returned a traffic challenge")
    parser = ScholarTableParser()
    parser.feed(html)
    parser.close()
    return parser.total_citations()


def fetch_profile() -> str:
    request = Request(
        PROFILE_URL,
        headers={
            "User-Agent": "yfyeung.github.io citation updater (+https://yfyeung.github.io/)",
            "Accept": "text/html",
            "Accept-Language": "en",
        },
    )
    # This is a socket timeout. The workflow also bounds the total fetch duration.
    with urlopen(request, timeout=20) as response:
        final_url = urlparse(response.url)
        if (
            response.status != 200
            or final_url.scheme != "https"
            or final_url.hostname != "scholar.google.com"
            or final_url.path != "/citations"
            or parse_qs(final_url.query).get("user") != [PROFILE_ID]
        ):
            raise ScholarUpdateError("Scholar did not return the requested public profile")
        if response.headers.get_content_type() != "text/html":
            raise ScholarUpdateError("Scholar did not return an HTML profile")
        body = response.read(MAX_HTML_BYTES + 1)
        if len(body) > MAX_HTML_BYTES:
            raise ScholarUpdateError("The Scholar response exceeded the expected page size")
        return body.decode(response.headers.get_content_charset() or "utf-8")


def write_snapshot(output: Path, snapshot: dict[str, object]) -> None:
    """Replace a snapshot atomically; failed writes leave an earlier file intact."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(snapshot, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o644)
        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def update_snapshot(output: Path, *, fetcher: Callable[[], str] = fetch_profile) -> dict[str, object]:
    total = parse_total_citations(fetcher())
    snapshot: dict[str, object] = {
        "profile_url": PROFILE_URL,
        "total_citations": total,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    write_snapshot(output, snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        snapshot = update_snapshot(args.output)
    except (ScholarUpdateError, URLError, OSError, UnicodeError) as error:
        print(f"Scholar update failed; the existing snapshot was kept: {error}", file=sys.stderr)
        return 1
    print(f"Updated Google Scholar total: {snapshot['total_citations']} ({snapshot['updated_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
