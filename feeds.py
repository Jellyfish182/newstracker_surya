"""RSS feed registry, fetching and date handling.

Every fetch records a diagnostic row so the UI can show exactly which feeds
were consulted, which ones responded, and what came back from each.
"""

import re
import gzip
import time
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser

# India Standard Time. RSS timestamps are normalised to this so every date on
# screen is in the reader's own timezone.
IST = timezone(timedelta(hours=5, minutes=30))

# Some feeds hang forever; cap every socket read.
socket.setdefaulttimeout(20)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# =====================================================================
# Feed registry
# =====================================================================
# Each entry is name -> (url, category). Category drives the grouping on
# the Sources tab.

FEEDS = {
    # --- National business press -------------------------------------
    "LiveMint - Companies": ("https://www.livemint.com/rss/companies", "National business"),
    "LiveMint - Industry": ("https://www.livemint.com/rss/industry", "National business"),
    "LiveMint - Technology": ("https://www.livemint.com/rss/technology", "National business"),
    "Economic Times - Industry": ("https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms", "National business"),
    "Economic Times - Tech": ("https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "National business"),
    "Business Standard - Companies": ("https://www.business-standard.com/rss/companies-101.rss", "National business"),
    "Business Standard - Economy": ("https://www.business-standard.com/rss/economy-policy-102.rss", "National business"),
    "CNBC TV18 - Business": ("https://www.cnbctv18.com/commonfeeds/v1/cne/rss/business.xml", "National business"),
    "CNBC TV18 - Companies": ("https://www.cnbctv18.com/commonfeeds/v1/cne/rss/companies.xml", "National business"),
    "BusinessLine - Companies": ("https://www.thehindubusinessline.com/companies/?service=rss", "National business"),
    "BusinessLine - Info Tech": ("https://www.thehindubusinessline.com/info-tech/?service=rss", "National business"),
    "BusinessLine - Economy": ("https://www.thehindubusinessline.com/economy/?service=rss", "National business"),

    # --- Sector verticals -------------------------------------------
    # Where capability centres, plants and data centres are actually reported.
    "ET Manufacturing": ("https://manufacturing.economictimes.indiatimes.com/rss/topstories", "Sector verticals"),
    "ET CIO / Enterprise IT": ("https://cio.economictimes.indiatimes.com/rss/topstories", "Sector verticals"),
    "ET Telecom": ("https://telecom.economictimes.indiatimes.com/rss/topstories", "Sector verticals"),
    "ET Real Estate": ("https://realty.economictimes.indiatimes.com/rss/topstories", "Sector verticals"),
    "ET Energy": ("https://energy.economictimes.indiatimes.com/rss/topstories", "Sector verticals"),

    # --- Startup / tech ----------------------------------------------
    "Inc42": ("https://inc42.com/feed/", "Startup and tech"),
    "YourStory": ("https://yourstory.com/feed", "Startup and tech"),
    "Entrackr": ("https://entrackr.com/rss", "Startup and tech"),

    # --- Regional: Telangana / Andhra Pradesh ------------------------
    "Telangana Today - Business": ("https://telanganatoday.com/business/feed", "AP / Telangana regional"),
    "Telangana Today - Latest": ("https://telanganatoday.com/feed", "AP / Telangana regional"),
    "The Hans India - Business": ("https://www.thehansindia.com/rss/business", "AP / Telangana regional"),
    "The Hans India - Telangana": ("https://www.thehansindia.com/rss/telangana", "AP / Telangana regional"),
    "The Hans India - Andhra Pradesh": ("https://www.thehansindia.com/rss/andhra-pradesh", "AP / Telangana regional"),
    "The Hindu - Andhra Pradesh": ("https://www.thehindu.com/news/national/andhra-pradesh/feeder/default.rss", "AP / Telangana regional"),
    "The Hindu - Telangana": ("https://www.thehindu.com/news/national/telangana/feeder/default.rss", "AP / Telangana regional"),

    # --- Targeted Google News queries --------------------------------
    # These surface event-shaped stories that the general feeds bury.
    "Google News - Hyderabad investment": (
        "https://news.google.com/rss/search?q=Hyderabad+(investment+OR+expansion+OR+%22new+facility%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
    "Google News - Telangana GCC": (
        "https://news.google.com/rss/search?q=Telangana+(GCC+OR+%22capability+centre%22+OR+%22global+centre%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
    "Google News - Andhra Pradesh investment": (
        "https://news.google.com/rss/search?q=%22Andhra+Pradesh%22+(investment+OR+MoU+OR+plant+OR+factory)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
    "Google News - Telangana industry": (
        "https://news.google.com/rss/search?q=Telangana+(factory+OR+plant+OR+%22industrial+park%22+OR+MoU)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
    "Google News - Hyderabad GCC hiring": (
        "https://news.google.com/rss/search?q=Hyderabad+(GCC+OR+%22global+capability%22+OR+hiring+OR+jobs)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
    "Google News - Visakhapatnam projects": (
        "https://news.google.com/rss/search?q=(Visakhapatnam+OR+Vizag+OR+Amaravati)+(project+OR+investment+OR+%22data+centre%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "Targeted search",
    ),
}


# =====================================================================
# Text and date helpers
# =====================================================================

_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#39;": "'", "&apos;": "'", "&nbsp;": " ", "&rsquo;": "'",
    "&lsquo;": "'", "&ldquo;": '"', "&rdquo;": '"',
    "&ndash;": "-", "&mdash;": "-",
}


def clean_text(value):
    """Strip HTML tags, decode common entities, collapse whitespace."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def parse_published(entry):
    """Return a timezone-aware IST datetime for an entry, or None.

    feedparser gives a UTC struct_time in *_parsed whenever it can understand
    the date. We prefer that over the raw string, which arrives in a dozen
    different formats across these publishers.
    """
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                utc_dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return utc_dt.astimezone(IST)
            except (ValueError, TypeError):
                continue
    return None


def format_absolute(dt):
    """'Mon, 24 Aug 2026 - 3:45 PM' - readable, unambiguous, no leading zero."""
    if dt is None:
        return "Date not published"
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%a, %d %b %Y')} · {hour}:{dt.strftime('%M %p')} IST"


def format_relative(dt, now=None):
    """'42 minutes ago', 'Yesterday', '3 days ago'."""
    if dt is None:
        return "Unknown"
    now = now or datetime.now(IST)
    seconds = (now - dt).total_seconds()

    if seconds < 0:
        return "Just published"
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = int(seconds // 86400)
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months != 1 else ''} ago"


def format_date_group(dt, now=None):
    """Bucket label used to group the opportunity list by day."""
    if dt is None:
        return "Undated"
    now = now or datetime.now(IST)
    today = now.date()
    day = dt.date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if 0 < (today - day).days < 7:
        return dt.strftime("%A")          # "Tuesday"
    return dt.strftime("%d %B %Y")        # "18 August 2026"


# =====================================================================
# Fetching
# =====================================================================

@dataclass
class FeedResult:
    """One feed's fetch outcome - the raw material for the Sources tab."""
    name: str
    url: str
    category: str
    status: str = "Pending"          # OK | Empty | Failed
    entry_count: int = 0
    candidate_count: int = 0         # entries that survived the region gate
    analysed_count: int = 0          # entries actually sent for AI analysis
    kept_count: int = 0              # entries the analysis confirmed
    elapsed_ms: int = 0
    http_status: int = 0
    newest: Optional[datetime] = None
    error: str = ""
    entries: list = field(default_factory=list)

    @property
    def ok(self):
        return self.status == "OK"


def _download(url):
    """Fetch feed bytes ourselves.

    feedparser's built-in fetcher mangles several of these publishers'
    responses (Moneycontrol, Financial Express and others come back as
    unparseable XML through it but are perfectly valid when handed over as
    raw bytes). Doing the HTTP ourselves also gives us a real status code
    to report on the Sources tab.
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        status = getattr(response, "status", 200)
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw, status


def _fetch_one(name, url, category):
    result = FeedResult(name=name, url=url, category=category)
    started = time.perf_counter()

    try:
        try:
            raw, result.http_status = _download(url)
            parsed = feedparser.parse(raw)
        except Exception as download_error:
            # Fall back to feedparser's own fetcher; it copes with a few
            # servers that reject our request shape.
            parsed = feedparser.parse(url, agent=USER_AGENT)
            if not parsed.entries:
                raise download_error

        # feedparser reports malformed XML on .bozo_exception but still
        # returns entries for merely-untidy markup, so only treat it as a
        # failure when nothing usable came back.
        if not parsed.entries:
            exc = getattr(parsed, "bozo_exception", None)
            if result.http_status and result.http_status >= 400:
                result.status = "Failed"
                result.error = f"HTTP {result.http_status}"
            elif exc is not None:
                result.status = "Failed"
                result.error = f"{type(exc).__name__}: {exc}"[:200]
            else:
                result.status = "Empty"
                result.error = "Feed returned no items"
            return result

        for entry in parsed.entries:
            title = clean_text(entry.get("title", ""))
            link = entry.get("link", "")
            if not title or not link:
                continue
            summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
            published = parse_published(entry)
            result.entries.append({
                "title": title,
                "summary": summary,
                "url": link,
                "published": published,
                "source": name,
                "source_category": category,
            })
            if published and (result.newest is None or published > result.newest):
                result.newest = published

        result.entry_count = len(result.entries)
        result.status = "OK" if result.entry_count else "Empty"

    except Exception as exc:                      # network, DNS, parse, timeout
        result.status = "Failed"
        result.error = f"{type(exc).__name__}: {exc}"[:200]

    finally:
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)

    return result


def fetch_all_feeds(max_workers=10, progress_callback=None):
    """Fetch every registered feed in parallel. Returns a list of FeedResult."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_one, name, url, category): name
            for name, (url, category) in FEEDS.items()
        }
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if progress_callback:
                progress_callback(done, len(futures), futures[future])

    results.sort(key=lambda r: r.name)
    return results
