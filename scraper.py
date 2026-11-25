#!/usr/bin/env python3
"""Crop Price Watch — Punjab, Pakistan.

Scrape publicly visible crop price tables for Garlic (Local), Carrot and Peas
from MandiOye and PakDataHub. Each execution creates ONE new timestamped raw
snapshot. Run the program separately on three collection days; do not change
collection timestamps to manufacture historical runs.

Install: pip install requests beautifulsoup4
Run:     python scraper.py
Output:  snapshots/full_snapshot_YYYY-MM-DD_HH-MM-SS.csv

Fields:
  crop, market, date (published price date), price (original source price),
  unit (original source unit), source, source_url, scraped_at (collection time),
  price_per_kg (normalized PKR/kg).

Notes:
* MandiOye uses the AMIS Fair Quotation Price (FQP) in PKR/100kg.
* PakDataHub lists a price in PKR/kg; entries may have older published dates.
* This script saves raw source observations, not a cleaned Tableau dataset.
* Do not mistake the date of scraping for the date of the actual price.
* HTML sites can change. Check parsing warnings and source pages after updates.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# The same crops and public pages used in our three-day project.
MANDIOYE_URLS = {
    "Garlic": "https://mandioye.com/amis/commodity/garlic-local",
    "Carrot": "https://mandioye.com/amis/commodity/carrot",
    "Peas": "https://mandioye.com/amis/commodity/peas",
}
PAKDATAHUB_URLS = {
    "Garlic": "https://pakdatahub.com/mandi/garlic_local",
    "Carrot": "https://pakdatahub.com/mandi/carrot",
    "Peas": "https://pakdatahub.com/mandi/peas",
}

USER_AGENT = "CropPriceWatchAcademic/1.0 (non-commercial university research)"
REQUEST_DELAY_SECONDS = 2.0
TIMEOUT_SECONDS = (10, 25)   # connect timeout, read timeout
MAX_ATTEMPTS = 3
MAX_MANDIOYE_PAGES = 20  # loop protection; follows 'Next' automatically
OUTPUT_DIR = Path("snapshots")
CSV_FIELDS = [
    "crop", "market", "date", "price", "unit", "price_per_kg",
    "source_url", "scraped_at", "source",
]

logger = logging.getLogger("crop_price_watch")


def parse_price(value: str) -> float | None:
    """Extract numeric prices from e.g. '33,500', 'Rs 210', or '62.5'."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return None
    amount = float(match.group().replace(",", ""))
    return amount if amount > 0 else None


def parse_price_date(value: str) -> str | None:
    """Convert a published price date to ISO yyyy-mm-dd; never guess a date."""
    cleaned = " ".join(str(value).strip().replace(",", " ").split())
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def collection_timestamp() -> str:
    """The exact time the request/row was collected (Pakistan local time)."""
    return datetime.now(ZoneInfo("Asia/Karachi")).isoformat(timespec="seconds")


class PoliteFetcher:
    """HTTP client: robots.txt checks, polite pacing, retry and error handling."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        })
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last_request_at: float | None = None

    def _wait(self) -> None:
        if self.last_request_at is not None:
            remaining = REQUEST_DELAY_SECONDS - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self.last_request_at = time.monotonic()

    def _request(self, url: str) -> requests.Response | None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait()
            try:
                response = self.session.get(url, timeout=TIMEOUT_SECONDS)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                logger.warning("Request %d/%d failed: %s (%s)",
                               attempt, MAX_ATTEMPTS, url, exc)
                if attempt < MAX_ATTEMPTS:
                    # Honor numeric Retry-After for 429/503; otherwise back off.
                    retry_after = None
                    resp = getattr(exc, "response", None)
                    if resp is not None:
                        retry_after = resp.headers.get("Retry-After")
                    pause = float(min(30, 2 ** attempt))
                    if retry_after:
                        try:
                            pause = min(60, max(pause, float(retry_after)))
                        except ValueError:
                            try:
                                parsed = parsedate_to_datetime(retry_after)
                                if parsed.tzinfo is None:
                                    parsed = parsed.replace(tzinfo=timezone.utc)
                                seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
                                pause = min(60, max(pause, seconds))
                            except (ValueError, TypeError, OverflowError):
                                pass
                    time.sleep(pause)
        logger.error("Skipping inaccessible URL after retries: %s", url)
        return None

    def _get_robots(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in self.robots:
            return self.robots[base]
        robots_url = base + "/robots.txt"
        logger.info("Checking robots.txt: %s", robots_url)
        # A 404 robots file is conventionally 'no published robots restrictions'.
        # Other HTTP errors or network problems are treated conservatively.
        self._wait()
        try:
            response = self.session.get(robots_url, timeout=TIMEOUT_SECONDS)
            if response.status_code in (404, 410):
                parser = RobotFileParser()
                parser.parse([])
                # Explicit wildcard allow if the site has no robots.txt.
                parser.parse(["User-agent: *", "Allow: /"])
                self.robots[base] = parser
                return parser
            response.raise_for_status()
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            self.robots[base] = parser
            return parser
        except requests.RequestException as exc:
            logger.error("Cannot verify robots.txt for %s: %s. Skipping site.", base, exc)
            self.robots[base] = None
            return None

    def get_html(self, url: str) -> str | None:
        parser = self._get_robots(url)
        if parser is None:
            return None
        if not parser.can_fetch(USER_AGENT, url):
            logger.warning("robots.txt disallows scraping: %s", url)
            return None
        response = self._request(url)
        return response.text if response is not None else None


def get_mandioye_date(soup: BeautifulSoup) -> str | None:
    """Read 'As of DD Mon YYYY' in the page, not the scraping date."""
    text = soup.get_text(" ", strip=True)
    match = re.search(r"\bAs\s+of\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", text, re.I)
    return parse_price_date(match.group(1)) if match else None


def find_table(soup: BeautifulSoup, required_headers: tuple[str, ...]):
    """Locate the relevant data table by column names, not CSS styling."""
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        headings = " ".join(c.get_text(" ", strip=True).lower()
                            for c in header_row.find_all(["th", "td"]))
        if all(header.lower() in headings for header in required_headers):
            return table
    return None


def next_page_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """Follow the visible 'Next' pagination link on the same commodity path."""
    current = urlparse(current_url)
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True).lower()
        if re.search(r"\bnext\b", label) or anchor.get("rel") == ["next"]:
            candidate = urljoin(current_url, anchor["href"])
            target = urlparse(candidate)
            if (target.netloc == current.netloc and target.path == current.path
                    and target.scheme == "https"):
                return candidate
    return None


def scrape_mandioye(fetcher: PoliteFetcher, crop: str, start_url: str) -> list[dict]:
    """Fetch all pages. FQP is originally quoted in PKR per 100 kilograms."""
    collected: list[dict] = []
    visited: set[str] = set()
    url: str | None = start_url
    page = 0

    while url and url not in visited and page < MAX_MANDIOYE_PAGES:
        visited.add(url)
        page += 1
        html = fetcher.get_html(url)
        if html is None:
            break
        soup = BeautifulSoup(html, "html.parser")
        published_date = get_mandioye_date(soup)
        if not published_date:
            logger.warning("No published 'As of' date found for %s; page ignored", url)
            break

        table = find_table(soup, ("fqp",))
        if table is None:
            logger.warning("Could not find City/FQP table on %s", url)
            break

        page_rows = 0
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            market = cells[1].get_text(" ", strip=True)
            original_price = parse_price(cells[5].get_text(" ", strip=True))
            if not market or original_price is None:
                continue
            collected.append({
                "crop": crop,
                "market": market,
                "date": published_date,
                "price": original_price,
                "unit": "PKR/100kg",
                "source": "mandioye.com",
                "source_url": url,
                "scraped_at": collection_timestamp(),
                "price_per_kg": round(original_price / 100.0, 4),
            })
            page_rows += 1
        logger.info("MandiOye | %s | page %d | price date %s | %d records",
                    crop, page, published_date, page_rows)
        url = next_page_url(soup, url)

    if url and page >= MAX_MANDIOYE_PAGES:
        logger.warning("MandiOye %s: hit pagination safety limit %d", crop, MAX_MANDIOYE_PAGES)
    return collected


def scrape_pakdatahub(fetcher: PoliteFetcher, crop: str, url: str) -> list[dict]:
    """Read public price table; keep only Punjab; price already PKR/kg."""
    html = fetcher.get_html(url)
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = find_table(soup, ("market", "province", "date"))
    if table is None:
        logger.warning("Could not find Market/Province/Date table: %s", url)
        return []

    collected: list[dict] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        market = cells[0].get_text(" ", strip=True)
        province = cells[1].get_text(" ", strip=True)
        if province.casefold() != "punjab":
            continue
        original_price = parse_price(cells[2].get_text(" ", strip=True))
        published_date = parse_price_date(cells[4].get_text(" ", strip=True))
        if not market or original_price is None or not published_date:
            continue
        collected.append({
            "crop": crop,
            "market": market,
            "date": published_date,
            "price": original_price,
            "unit": "PKR/kg",
            "source": "pakdatahub.com",
            "source_url": url,
            "scraped_at": collection_timestamp(),
            "price_per_kg": round(original_price, 4),
        })
    logger.info("PakDataHub | %s | Punjab | %d records", crop, len(collected))
    return collected


def save_snapshot(rows: list[dict], folder: Path = OUTPUT_DIR) -> Path:
    """One uniquely named, immutable output file for this collection run."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Karachi")).strftime("%Y-%m-%d_%H-%M-%S")
    destination = folder / f"full_snapshot_{stamp}.csv"
    # Mode 'x' prevents overwriting an older snapshot.
    with destination.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s", stream=sys.stdout)
    fetcher = PoliteFetcher()
    rows: list[dict] = []
    source_counts = {"mandioye.com": 0, "pakdatahub.com": 0}

    for crop, url in MANDIOYE_URLS.items():
        result = scrape_mandioye(fetcher, crop, url)
        rows.extend(result)
        source_counts["mandioye.com"] += len(result)
    for crop, url in PAKDATAHUB_URLS.items():
        result = scrape_pakdatahub(fetcher, crop, url)
        rows.extend(result)
        source_counts["pakdatahub.com"] += len(result)

    if not rows:
        logger.error("No records collected. Nothing saved; check robots.txt, connectivity and HTML.")
        return 1

    path = save_snapshot(rows)
    print("\n--- Crop Price Watch ---")
    print("Region: Punjab, Pakistan | Crops: Garlic, Carrot, Peas")
    print("MandiOye records:", source_counts["mandioye.com"])
    print("PakDataHub records:", source_counts["pakdatahub.com"])
    print("Total raw records:", len(rows))
    print("Published price dates:", sorted({r["date"] for r in rows}))
    print("Saved snapshot:", path.resolve())
    if not all(source_counts.values()):
        logger.warning("Only one source returned data: snapshot is PARTIAL.")
    if len(rows) < 300:
        logger.warning("Fewer than 300 rows in this run. Check source coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())