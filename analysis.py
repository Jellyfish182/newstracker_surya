"""Lead identification for a Big 4 direct tax practice in AP / Telangana.

The user is a direct tax consultant looking for NEW CLIENTS to pitch. A result
is only useful if it names a company they could actually telephone about an
event that is landing in Telangana or Andhra Pradesh. Everything else - policy
announcements with no company, market commentary, sector round-ups, stories
about other states - is noise, however business-shaped it looks.

Three stages:

  1. A region gate keeps articles that genuinely refer to AP or Telangana.
  2. A lead gate demands a named corporate actor and a concrete, committed
     event of a type that generates tax work.
  3. Claude reads the survivors and makes the real judgement, extracting the
     company, the numbers, the service lines and an evidence quote.

Without an API key the module falls back to a strict keyword scorer. That
fallback is precision-first by design: it would rather miss a lead than hand
over a page of stories that are not leads.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# --------------------------------------------------------------------
# Region gate
# --------------------------------------------------------------------

REGION_TERMS = {
    "Telangana": [
        "telangana", "hyderabad", "secunderabad", "rangareddy", "ranga reddy",
        "medchal", "madhapur", "gachibowli", "hitec city", "hi-tech city",
        "hitech city", "financial district", "genome valley", "shamshabad",
        "warangal", "t-hub", "kompally", "nanakramguda", "kokapet",
        "sangareddy", "patancheru", "jadcherla", "karimnagar", "nizamabad",
        "adibatla", "pocharam", "raviryal", "mucherla", "zahirabad",
    ],
    "Andhra Pradesh": [
        "andhra pradesh", "visakhapatnam", "vizag", "vijayawada", "amaravati",
        "guntur", "tirupati", "kurnool", "nellore", "kakinada", "rajahmundry",
        "anantapur", "sri city", "krishnapatnam", "chittoor", "kadapa",
        "ongole", "machilipatnam", "bhogapuram", "orvakal", "rayalaseema",
        "atchutapuram", "naidupeta", "kopparthy",
    ],
}

_BARE_ANDHRA = re.compile(r"\bandhra\b")

MAX_CANDIDATES = 140
BATCH_SIZE = 10          # more articles per request = system prompt amortised
MAX_WORKERS = 5

# Models offered in the sidebar, cheapest first.
#
# "supports_effort" matters: the effort setting and adaptive thinking exist
# only on the newer models. Sending either to Haiku 4.5 returns a 400, so the
# request has to be shaped per model rather than assuming one format.
MODELS = {
    "claude-haiku-4-5": {
        "label": "Haiku 4.5 - cheapest",
        "input_per_mtok": 1.0,
        "output_per_mtok": 5.0,
        "supports_effort": False,
        "note": "About 5x cheaper than Opus. Good for straightforward screening.",
    },
    "claude-sonnet-5": {
        "label": "Sonnet 5 - balanced",
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
        "supports_effort": True,
        "note": "Middle ground on cost and judgement.",
    },
    "claude-opus-5": {
        "label": "Opus 5 - most accurate",
        "input_per_mtok": 5.0,
        "output_per_mtok": 25.0,
        "supports_effort": True,
        "note": "Best at rejecting borderline stories. Highest cost.",
    },
}

DEFAULT_MODEL = "claude-haiku-4-5"

# Google's free tier. No card required, so this is the default engine.
# Rate limits are per-minute rather than per-dollar, hence the lower
# concurrency and the backoff in _gemini_batch.
GEMINI_MODELS = {
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash - free",
        "note": "Free tier. Reads each article properly. Best free option.",
    },
    "gemini-2.5-flash-lite": {
        "label": "Gemini 2.5 Flash Lite - free, fastest",
        "note": "Free tier with a higher request allowance. Slightly blunter judgement.",
    },
    "gemini-2.0-flash": {
        "label": "Gemini 2.0 Flash - free, fallback",
        "note": "Use if the 2.5 models are unavailable in your region.",
    },
}

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

GEMINI_WORKERS = 2       # free tier throttles by requests per minute
GEMINI_RETRIES = 4


def estimate_cost(model, input_tokens, output_tokens):
    """Cost in USD for one scan, using the selected model's own rates."""
    pricing = MODELS.get(model)
    if not pricing:
        return 0.0
    return round(
        (input_tokens / 1_000_000) * pricing["input_per_mtok"]
        + (output_tokens / 1_000_000) * pricing["output_per_mtok"],
        4,
    )

# Event types that produce direct tax work and a client to approach.
# Deliberately excludes hiring-only stories and government policy news:
# neither gives you a company to pitch.
EVENT_TYPES = [
    "New GCC / Capability Centre",
    "Foreign Subsidiary / India Entry",
    "New Entity / Company Incorporation",
    "Office / Campus Setup",
    "Manufacturing Plant / Project",
    "Data Centre",
    "R&D / Innovation Centre",
    "Major Investment / Capex",
    "M&A / JV",
    "Expansion of Existing Operations",
]

SERVICE_LINES = [
    "Corporate Tax",
    "Transfer Pricing",
    "International Tax / Treaty",
    "Permanent Establishment Risk",
    "Entity Setup / Incorporation",
    "FEMA / Regulatory",
    "State Incentives",
    "M&A / Deal Tax",
    "Expatriate / Payroll Tax",
    "Withholding Tax",
]


# --------------------------------------------------------------------
# Noise definitions
# --------------------------------------------------------------------

OFF_TOPIC_TERMS = [
    # sport
    "cricket", "badminton", "kabaddi", "football", "hockey", "olympic",
    "tournament", "championship", "world cup", "wickets", "medal", "athlete",
    "trophy", "match against", "innings",
    # crime, courts, accidents
    "murder", "rape", "arrest", "police", "custody", "accident", "mishap",
    "died", "dead body", "suicide", "assault", "kidnap", "smuggl",
    "blast", "explosion", "fire breaks", "blaze", "gas leak", "casualt",
    "injured", "toll rises", "rescue", "collapse", "mishap at",
    "drunk driving", "encounter", "court sentences", "acquitted", "bail",
    # civic, weather, human interest
    "rainfall", "cyclone", "heatwave", "monsoon", "temple", "festival",
    "devotees", "obituary", "passes away", "condolence", "anniversary",
    "movie", "actor", "actress", "box office", "tollywood", "film star",
    "horoscope", "recipe", "wedding", "traffic", "power cut", "water supply",
    "medical camp", "health camp", "blood donation", "awareness camp",
    "free medical", "scholarship", "admission", "exam result", "syllabus",
    "protest", "dharna", "strike", "bandh", "agitation",
    # electoral politics
    "election", "poll survey", "vote share", "by-election", "assembly session",
    "no-confidence", "party workers", "opposition leader", "cabinet reshuffle",
    "manifesto", "campaign trail",
    # market noise
    "share price", "shares rise", "shares fall", "stock rises", "stock falls",
    "stock jumps", "multibagger", "dividend", "sensex", "nifty", "price target",
    "brokerage", "buy or sell", "listing gains", "ipo allotment", "bonus issue",
    "quarterly results", "q1 results", "q2 results", "q3 results", "q4 results",
    "net profit", "profit rises", "revenue rises", "earnings call",
    "52-week high", "52-week low", "market cap", "analyst",
]

# Round-ups and listicles mention many companies without being about any of
# them. They score highly on any keyword measure and are never a lead.
ROUNDUP_TERMS = [
    "this week", "last week", "weekly", "roundup", "round-up", "wrap-up",
    "top 10", "top 5", "top five", "top ten", "list of", "here are",
    "highlights", "in pictures", "explained", "what to expect", "preview",
    "recap", "digest", "newsletter", "biggest stories", "key takeaways",
    "funding and acquisitions", "deals of the",
]

# When only these appear as the actor, there is no private client to pitch.
GOVERNMENT_ACTORS = [
    "government", "govt", "cabinet", "minister", "chief minister", "cm ",
    "ministry", "department of", "state to", "centre to", "niti aayog",
    "municipal", "corporation of", "authority", "board approves",
]

# --------------------------------------------------------------------
# Lead signals
# --------------------------------------------------------------------

# A concrete, committed corporate action. One of these must be present for a
# story to be treated as a lead. Weak words like "investment" on their own are
# deliberately absent - they match half the business press.
STRONG_EVENT_PATTERNS = [
    # capability centres
    (r"\b(gcc|global capability cent(re|er)|capability cent(re|er)|"
     r"global (delivery|development) cent(re|er)|shared services cent(re|er)|"
     r"global in-?house cent(re|er))\b", "New GCC / Capability Centre", 42),
    # india entry / subsidiary
    (r"\b(wholly[- ]owned subsidiary|subsidiary in india|indian subsidiary|"
     r"india subsidiary|enters india|entering india|india entry|"
     r"forays into india|sets? up (its )?india|first india)\b",
     "Foreign Subsidiary / India Entry", 40),
    # incorporation
    (r"\b(incorporat(es|ed|ion)|registers? (a )?(new )?(company|entity)|"
     r"new entity|floats? (a )?(new )?(company|arm|unit))\b",
     "New Entity / Company Incorporation", 36),
    # data centre
    (r"\b(data cent(re|er)|hyperscale|cloud region|colocation)\b",
     "Data Centre", 38),
    # plant / manufacturing
    (r"\b(manufacturing (plant|facility|unit)|new plant|greenfield|"
     r"production facility|assembly (plant|line)|fabrication|"
     r"semiconductor (fab|plant|unit)|bulk drug (unit|park)|"
     r"pharma (plant|unit)|breaks? ground)\b",
     "Manufacturing Plant / Project", 38),
    # r&d
    (r"\b(r&d cent(re|er)|research (and development )?cent(re|er)|"
     r"innovation cent(re|er)|engineering cent(re|er)|"
     r"technology cent(re|er)|design cent(re|er))\b",
     "R&D / Innovation Centre", 36),
    # office / campus
    (r"\b(new (office|campus|facility)|opens? (an? )?(office|campus|facility|cent(re|er))|"
     r"inaugurat(es|ed)|leases? .{0,25}(office|sq ft)|"
     r"sets? up (an? )?(office|campus|facility|cent(re|er))|"
     r"to set up (an? )?(office|campus|facility|cent(re|er)))\b",
     "Office / Campus Setup", 34),
    # M&A
    (r"\b(acquires?|acquisition of|to acquire|joint venture|"
     r"buys? (a )?(majority |minority )?stake|merger with)\b", "M&A / JV", 30),
    # expansion
    (r"\b(expands? (its )?(operations|presence|facility|capacity)|"
     r"expansion (of|plan)|second (campus|facility|cent(re|er))|"
     r"scales? up operations)\b", "Expansion of Existing Operations", 28),
]

# A committed investment with a real figure attached.
INVESTMENT_PATTERNS = [
    r"(?:invest|investment|capex|outlay|commit(?:s|ted|ment)?|infus(?:e|es|ion))"
    r"[^.]{0,60}?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh crore)",
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh crore)"
    r"[^.]{0,60}?(?:invest|investment|capex|project|facility|plant|unit)",
    r"(?:invest|investment|capex|outlay|commit(?:s|ted|ment)?)"
    r"[^.]{0,60}?(?:\$|usd)\s*([\d,]+(?:\.\d+)?)\s*(million|billion|mn|bn)",
]

# Foreign-origin markers - these leads carry the most direct tax work
# (treaty, PE risk, transfer pricing, FEMA).
FOREIGN_MARKERS = [
    "us-based", "u.s.-based", "uk-based", "japan-based", "german", "germany-based",
    "swiss", "switzerland", "singapore-based", "dutch", "netherlands",
    "french", "france-based", "korean", "korea-based", "chinese", "taiwan",
    "australian", "canadian", "danish", "swedish", "israeli", "multinational",
    "mnc", "global major", "fortune 500", "headquartered in", "foreign",
    "american", "european", "japanese", "british",
]

# Corporate-name markers used to confirm a real company is named.
COMPANY_SUFFIXES = [
    "ltd", "limited", "inc", "inc.", "corp", "corporation", "llc", "llp",
    "plc", "gmbh", "ag", "sa", "nv", "bv", "pvt", "private", "co.",
    "technologies", "technology", "systems", "solutions", "labs",
    "laboratories", "pharma", "pharmaceuticals", "industries", "enterprises",
    "group", "holdings", "ventures", "motors", "electronics", "semiconductor",
    "energy", "infra", "infrastructure", "logistics", "healthcare", "bank",
    "capital", "consulting", "services", "software", "networks", "digital",
]

# Lead-in noise to strip before reading a company name off a headline.
_QUALIFIER_PREFIX = re.compile(
    r"^(?:the\s+)?(?:us|u\.s\.|uk|german|japanese|swiss|korean|chinese|french|"
    r"dutch|israeli|american|european|british|australian|canadian|singapore|"
    r"taiwan(?:ese)?|global|multinational|mnc|leading|major|top|city-based|"
    r"hyderabad-based|bengaluru-based|mumbai-based|delhi-based|india-based|"
    r"[a-z]+-based)\s+"
    r"(?:financial\s+services\s+|technology\s+|software\s+|pharma\s+|"
    r"engineering\s+|manufacturing\s+|it\s+|auto\s+)?"
    r"(?:firm|company|giant|major|player|group|maker|provider|conglomerate)\s+",
    re.IGNORECASE,
)


def detect_regions(text):
    """Which of the two target states this text plausibly refers to."""
    lower = text.lower()
    found = [r for r, terms in REGION_TERMS.items() if any(t in lower for t in terms)]
    if "Andhra Pradesh" not in found and _BARE_ANDHRA.search(lower):
        if any(w in lower for w in ("state", "government", "chief minister",
                                    "investment", "plant", "project", "district")):
            found.append("Andhra Pradesh")
    return found


def _dedupe_key(title):
    """Normalised title used to spot the same story arriving twice.

    Google News appends " - Publisher Name" to every headline, so the same
    wire story shows up under several suffixes. Strip that before comparing.
    """
    stripped = re.sub(r"\s+[-|]\s+[^-|]{2,40}$", "", title.strip())
    return re.sub(r"[^a-z0-9]+", "", stripped.lower())[:90]


def is_off_topic(text):
    lower = text.lower()
    return any(term in lower for term in OFF_TOPIC_TERMS)


def is_roundup(title):
    lower = title.lower()
    return any(term in lower for term in ROUNDUP_TERMS)


def find_event(text):
    """Strongest concrete event in the text. Returns (event, weight) or None."""
    lower = text.lower()
    hits = [(event, weight) for pattern, event, weight in STRONG_EVENT_PATTERNS
            if re.search(pattern, lower)]
    return max(hits, key=lambda h: h[1]) if hits else None


def find_investment(text):
    """Committed investment figure, normalised to INR crore. None if absent."""
    lower = text.lower().replace("₹", "rs ")
    for pattern in INVESTMENT_PATTERNS:
        match = re.search(pattern, lower)
        if not match:
            continue
        try:
            amount = float(match.group(1).replace(",", ""))
        except (ValueError, IndexError):
            continue
        unit = (match.group(2) or "").strip() if match.lastindex and match.lastindex >= 2 else ""
        if unit in ("lakh crore",):
            return amount * 100_000
        if unit in ("crore", "cr"):
            return amount
        if unit in ("billion", "bn"):
            return amount * 8_300          # USD bn -> INR crore at 83
        if unit in ("million", "mn"):
            return amount * 8.3            # USD mn -> INR crore
        return amount
    return None


# Tokens that end a company name. Title-case headlines ("Charles Schwab To Add
# 2,000 Employees") sweep verbs into the capitalised run, so the name has to be
# cut at the first of these rather than merely trimmed at the end.
_NAME_STOP_WORDS = {
    "to", "opens", "open", "opened", "opening", "launches", "launch", "launched",
    "plans", "plan", "planned", "planning", "sets", "set", "setting", "enters",
    "enter", "entering", "announces", "announce", "announced", "invests",
    "invest", "investing", "acquires", "acquire", "acquired", "buys", "buy",
    "expands", "expand", "expanding", "leases", "lease", "leased", "adds",
    "add", "adding", "signs", "sign", "signed", "picks", "pick", "picked",
    "eyes", "eye", "eyeing", "commits", "commit", "gets", "get", "may",
    "will", "is", "are", "has", "have", "said", "says", "say", "to", "in",
    "at", "on", "for", "with", "from", "approves", "approve", "approved",
    "unveils", "unveil", "unveiled", "starts", "start", "started", "begins",
    "begin", "readies", "ready", "mulls", "mull", "weighs", "weigh", "ties",
    "tie", "partners", "partner", "raises", "raise", "raised", "inaugurates",
    "inaugurate", "inaugurated", "boosts", "boost", "names", "name", "named",
    "appoints", "appoint", "hires", "hire", "hiring", "moves", "move", "wins",
    "win", "won", "posts", "post", "reports", "report", "sees", "see",
    "proposes", "propose", "proposed", "shifts", "shift", "shifted",
    "busts", "bust", "mulls", "holds", "held", "seeks", "seek", "urges",
    "urge", "calls", "call", "flags", "flag", "backs", "back", "clears",
    "clear", "cleared", "allots", "allot", "grants", "grant", "offers",
    "offer", "targets", "target", "eyes", "denies", "deny", "confirms",
    "confirm", "reveals", "reveal", "marks", "mark", "opens", "around",
    "over", "amid", "after", "before", "despite", "against", "among",
}

# Never a prospective client: political parties, government bodies, and
# generic headline lead-ins that look like proper nouns.
_NON_COMPANY_NAMES = {
    # political parties
    "ysrcp", "ysr congress", "tdp", "telugu desam", "bjp", "brs", "trs",
    "congress", "aap", "janasena", "jana sena", "cpi", "cpm", "mim", "aimim",
    # government and public bodies
    "ap", "andhra", "andhra pradesh", "telangana", "government", "govt",
    "state", "centre", "center", "cabinet", "ministry", "minister", "cm",
    "chief minister", "assembly", "parliament", "india", "gsi", "niti aayog",
    "supreme court", "high court", "police", "collector", "municipal",
    "railway", "railways", "isro", "drdo", "rbi", "sebi", "cbi", "ed",
    "hmda", "ghmc", "tsiic", "apiic", "sipb", "cgst", "gst council",
    "income tax department", "customs",
    # politicians frequently named at the head of regional headlines
    "naidu", "chandrababu", "chandrababu naidu", "lokesh", "nara lokesh",
    "jagan", "jagan mohan", "ys jagan", "revanth", "revanth reddy", "ktr",
    "kcr", "harish rao", "modi", "amit shah", "sitharaman", "bhatti",
    "vikramarka", "sridhar babu", "ponguleti",
    # generic headline lead-ins
    "the", "a", "an", "new", "this", "that", "here", "how", "why", "what",
    "when", "where", "who", "top", "best", "first", "india's", "telangana's",
    "andhra's", "hyderabad's", "vizag's", "state's", "country's", "world's",
    "exclusive", "breaking", "watch", "video", "opinion", "explained",
}


# Common headline nouns that survive capitalisation in title-case headlines
# but are obviously not companies ("Concerns Over Data Centre...").
_GENERIC_NOUNS = {
    "concerns", "plans", "work", "deal", "deals", "project", "projects",
    "report", "reports", "growth", "jobs", "land", "power", "energy", "water",
    "roads", "budget", "scheme", "policy", "summit", "meet", "talks", "push",
    "boost", "focus", "future", "demand", "supply", "prices", "sector",
    "industry", "business", "economy", "market", "markets", "investment",
    "investments", "companies", "firms", "startups", "students", "farmers",
    "residents", "citizens", "people", "officials", "experts", "leaders",
    "development", "infrastructure", "construction", "expansion", "setup",
    "free", "new", "more", "big", "huge", "major", "several", "many", "few",
    "two", "three", "four", "five", "over", "under", "after", "before",
}


def _is_non_company(name):
    lower = re.sub(r"['’]s$", "", name.lower().strip(" .,")).strip()
    words = lower.split()
    if not words:
        return True
    if lower in _NON_COMPANY_NAMES or lower in _GENERIC_NOUNS:
        return True

    first = words[0]
    if first in _NON_COMPANY_NAMES or first in _GENERIC_NOUNS:
        return True

    # A place-led name ("Vizag Google Data Centre", "Western Hyderabad") is a
    # headline fragment, not a client - unless a corporate suffix follows.
    all_places = {p for terms in REGION_TERMS.values() for p in terms}
    if first in all_places or (len(words) > 1 and words[1] in all_places):
        if not any(w.strip(".,") in COMPANY_SUFFIXES for w in words):
            return True

    # A single generic capitalised word is almost never a company. Allow
    # acronyms (CIBC, HSBC) and CamelCase brands (PepsiCo).
    if len(words) == 1:
        original_ok = name.isupper() or any(c.isupper() for c in name[1:])
        if not original_ok and lower in _GENERIC_NOUNS:
            return True

    return False


def extract_company(title):
    """Best-effort company name from a headline.

    Strips lead-in qualifiers ("US financial services firm ..."), then cuts the
    capitalised run at the first verb or preposition. Without that cut,
    title-case headlines yield names like "Charles Schwab To" or
    "Acumatica Opens Global Cap".
    """
    cleaned = _QUALIFIER_PREFIX.sub("", title.strip())
    cleaned = re.sub(r"^(exclusive|breaking|update|watch|video)\s*[:|-]\s*", "",
                     cleaned, flags=re.IGNORECASE)

    match = re.match(
        r"^((?:[A-Z][\w&.\-']*|of|and|de|van|\d+)(?:\s+(?:[A-Z][\w&.\-']*|of|and|de|van))*)",
        cleaned,
    )
    if not match:
        return None

    tokens = match.group(1).split()
    kept = []
    for token in tokens:
        if token.lower().strip(".,:;") in _NAME_STOP_WORDS:
            break
        kept.append(token)

    name = " ".join(kept).strip(" -:|,.'")
    if not name or len(name) < 3 or len(kept) > 6:
        return None
    if _is_non_company(name):
        return None
    return name


def has_named_company(title, text):
    """True when a specific, pitchable company appears to be named."""
    lower = text.lower()
    if any(f" {suffix} " in f" {lower} " or lower.endswith(f" {suffix}")
           for suffix in COMPANY_SUFFIXES):
        return True
    company = extract_company(title)
    if not company:
        return False
    # Reject when the only actor is the state.
    if any(actor in company.lower() for actor in GOVERNMENT_ACTORS):
        return False
    return len(company.split()) >= 1 and company.lower() not in (
        "the", "a", "an", "new", "india", "telangana", "andhra", "hyderabad",
    )


def is_government_only(title, text):
    """True when the state is the actor and no company is named."""
    lower = f"{title} {text}".lower()
    mentions_govt = any(actor in lower for actor in GOVERNMENT_ACTORS)
    return mentions_govt and not has_named_company(title, text)


def lead_signal(title, summary):
    """Ranking score for how likely this is a pitchable lead.

    Used to order candidates so the article cap is spent well. The real
    accept/reject decision happens later.
    """
    text = f"{title}. {summary}"
    lower = text.lower()
    score = 0

    event = find_event(text)
    if event:
        score += event[1]

    investment = find_investment(text)
    if investment:
        score += 12
        if investment >= 1_000:
            score += 8
        if investment >= 10_000:
            score += 6

    if any(marker in lower for marker in FOREIGN_MARKERS):
        score += 10
    if has_named_company(title, text):
        score += 12
    if re.search(r"\b([1-9]\d{2,}|\d{1,3},\d{3})\s+(jobs|employees|professionals|people)\b", lower):
        score += 6

    # Region named in the headline itself is a much stronger locality signal
    # than a passing mention buried in the summary.
    if detect_regions(title):
        score += 10

    if is_roundup(title):
        score -= 30
    if is_government_only(title, text):
        score -= 15

    return score


def prefilter(feed_results, max_candidates=MAX_CANDIDATES):
    """Stage 1 + 2. Returns (candidates, stats).

    Applies the region gate, then a lead gate that demands a concrete event
    and a named company. Round-ups, policy-only stories and off-topic
    subjects are dropped outright rather than passed on to be analysed.
    """
    candidates = []
    seen_urls, seen_titles = set(), set()
    counters = {"total_entries": 0, "duplicates": 0, "off_topic": 0,
                "roundup": 0, "no_event": 0, "no_company": 0, "government_only": 0}

    for feed in feed_results:
        for entry in feed.entries:
            counters["total_entries"] += 1

            url = entry["url"]
            title_key = _dedupe_key(entry["title"])
            if url in seen_urls or (title_key and title_key in seen_titles):
                counters["duplicates"] += 1
                continue

            title, summary = entry["title"], entry["summary"]
            combined = f"{title}. {summary}"

            regions = detect_regions(combined)
            if not regions:
                continue

            seen_urls.add(url)
            if title_key:
                seen_titles.add(title_key)

            if is_off_topic(combined):
                counters["off_topic"] += 1
                continue
            if is_roundup(title):
                counters["roundup"] += 1
                continue

            event = find_event(combined)
            investment = find_investment(combined)
            # A story qualifies on a concrete event, or on a committed
            # investment figure of real size.
            if not event and not (investment and investment >= 100):
                counters["no_event"] += 1
                continue
            if not has_named_company(title, combined):
                counters["no_company"] += 1
                continue
            if is_government_only(title, combined):
                counters["government_only"] += 1
                continue

            candidate = dict(entry)
            candidate["regions"] = regions
            candidate["signal"] = lead_signal(title, summary)
            candidate["event_guess"] = event[0] if event else "Major Investment / Capex"
            candidate["investment_guess"] = investment
            candidates.append(candidate)
            feed.candidate_count += 1

    oldest = datetime.min.replace(tzinfo=timezone.utc)
    candidates.sort(key=lambda c: (c["signal"], c["published"] or oldest), reverse=True)
    capped = candidates[:max_candidates]

    stats = dict(counters)
    stats.update({
        "qualified_leads": len(candidates),
        "sent_for_analysis": len(capped),
        "dropped_by_cap": len(candidates) - len(capped),
    })
    return capped, stats


# --------------------------------------------------------------------
# Claude analysis
# --------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are screening Indian business news for a DIRECT TAX PARTNER at a \
Big 4 firm based in Hyderabad. The partner's goal is narrow and commercial: find companies \
they can telephone this week and pitch for new direct tax work in TELANGANA or ANDHRA PRADESH.

A result is only useful if it gives the partner (a) a named company to call, and (b) a \
concrete event landing in one of those two states that creates tax work.

MARK relevant=true ONLY when ALL FOUR of these hold:

1. NAMED COMPANY. A specific, identifiable corporate entity is named - the prospective \
client. "The Telangana government", "the IT sector", "industry players", "investors" are \
NOT companies. If the only actor is a government body, relevant=false.

2. LOCATED IN TELANGANA OR ANDHRA PRADESH. The facility, entity, investment or project \
must physically land in one of those two states. Reject when the state is mentioned only \
in passing - a Hyderabad-headquartered company investing in Pune is NOT a lead; a \
conference held in Hyderabad about national policy is NOT a lead; a company that merely \
"also has an office in Hyderabad" is NOT a lead.

3. CONCRETE AND COMMITTED. An actual announced or completed action: a centre opened, an \
entity incorporated, land acquired, a plant commissioned, an MoU signed with a named \
party, a stated investment figure, a deal closed. Reject aspiration and speculation - \
"plans to explore", "may consider", "is in talks", "state hopes to attract", \
"sector could see" are all relevant=false.

4. GENERATES DIRECT TAX WORK. The event type must be one of: {", ".join(EVENT_TYPES)}.

ALWAYS set relevant=false for:
- Share prices, results, earnings, analyst notes, IPO and market commentary.
- Sector round-ups, weekly funding wrap-ups, listicles, "top 10" pieces - these name many \
companies but are about none of them.
- Government schemes, budgets, policy announcements and ministerial statements where no \
private company is named as the investor.
- Hiring news on its own, with no new facility, entity or investment behind it.
- Product launches, app releases, marketing campaigns, awards, rankings, appointments, \
interviews and opinion columns.
- Events in other states, or national-level news with an incidental AP/Telangana mention.
- Stories where the underlying event clearly happened years ago.

Be strict. The partner would far rather receive four solid leads than forty maybes. When \
in doubt, reject. Never invent a company name, an investment figure or a headcount that \
is not in the text - use null instead.

FIELD RULES:
- company: the prospective client's name, exactly as a partner would say it on a call. \
Strip qualifiers: "US financial services firm Charles Schwab" is "Charles Schwab".
- event_type: exactly one of: {", ".join(EVENT_TYPES)}
- location: the most specific place named (e.g. "Kokapet, Hyderabad"). Must be in \
Telangana or Andhra Pradesh.
- foreign_parent: true when the investing entity is foreign-owned or foreign-headquartered. \
These carry treaty, PE and transfer pricing work, so they matter most.
- investment_inr_crore: the figure in INR crore. Convert USD at 83. null if not stated.
- jobs: headcount stated in the article. null if not stated.
- tax_services: 1 to 4 entries from: {", ".join(SERVICE_LINES)}
- pitch_note: two sentences maximum, written for the partner before dialling. First what \
the company is doing and where; second the specific direct tax angle to lead with. No \
filler, no restating the headline.
- evidence: a short quoted fragment from the supplied text proving the event and the \
location. It must actually appear in the text - this is how the partner audits you.
- confidence: 0-100, how certain you are this is a real lead as described. Below 50 means \
the summary was too thin to be sure.
- priority_score: 0-100 commercial value. Weigh deal size, foreign parent, whether the \
entity is new to the state, and the volume of tax work created. A foreign multinational \
incorporating its first Indian subsidiary and building a GCC in Hyderabad is near 100. A \
local firm taking one extra floor of office space is near 30.

Return one result object per input article, in the same order, with the same id."""


RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "reject_reason": {"type": ["string", "null"]},
                    "company": {"type": ["string", "null"]},
                    "event_type": {"type": ["string", "null"], "enum": EVENT_TYPES + [None]},
                    "location": {"type": ["string", "null"]},
                    "foreign_parent": {"type": "boolean"},
                    "investment_inr_crore": {"type": ["number", "null"]},
                    "jobs": {"type": ["integer", "null"]},
                    "tax_services": {"type": "array",
                                     "items": {"type": "string", "enum": SERVICE_LINES}},
                    "pitch_note": {"type": ["string", "null"]},
                    "evidence": {"type": ["string", "null"]},
                    "confidence": {"type": "integer"},
                    "priority_score": {"type": "integer"},
                },
                "required": [
                    "id", "relevant", "reject_reason", "company", "event_type",
                    "location", "foreign_parent", "investment_inr_crore", "jobs",
                    "tax_services", "pitch_note", "evidence", "confidence",
                    "priority_score",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def get_api_key():
    """Resolve the key from Streamlit secrets first, then the environment."""
    try:
        import streamlit as st
        if "ANTHROPIC_API_KEY" in st.secrets:
            return str(st.secrets["ANTHROPIC_API_KEY"]).strip()
    except Exception:
        pass
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def ai_available(api_key=None):
    key = api_key if api_key is not None else get_api_key()
    if not key:
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _format_batch(batch):
    lines = []
    for idx, article in enumerate(batch):
        published = article["published"]
        when = published.strftime("%d %b %Y") if published else "date not given"
        lines.append(
            f'<article id="{idx}">\n'
            f"Headline: {article['title']}\n"
            f"Summary: {article['summary'][:900] or '(no summary provided)'}\n"
            f"Source: {article['source']}\n"
            f"Published: {when}\n"
            f"</article>"
        )
    return ("Screen each article below and return one result object per article.\n\n"
            + "\n\n".join(lines))


def _analyse_batch(client, batch, model, effort):
    request = {
        "model": model,
        "max_tokens": 8000,
        # The rubric is identical on every request, so cache it: repeat calls
        # read it back at a tenth of the input price.
        "system": [{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        "output_config": {"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        "messages": [{"role": "user", "content": _format_batch(batch)}],
    }

    # Adaptive thinking and the effort dial exist only on the newer models;
    # sending either to Haiku 4.5 is rejected with a 400.
    if MODELS.get(model, {}).get("supports_effort"):
        request["thinking"] = {"type": "adaptive"}
        request["output_config"]["effort"] = effort

    response = client.messages.create(**request)

    if response.stop_reason == "refusal":
        raise RuntimeError("Analysis declined by safety filter for this batch")

    text = next((b.text for b in response.content if b.type == "text"), "")
    payload = json.loads(text)
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return payload.get("results", []), usage


def analyse_with_ai(candidates, api_key, model=DEFAULT_MODEL, effort="medium",
                    progress_callback=None):
    """Stage 3. Returns (leads, rejected, telemetry)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=3)
    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]
    leads, rejected, errors = [], [], []
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0}

    def run(index, batch):
        results, usage = _analyse_batch(client, batch, model, effort)
        return index, batch, results, usage

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run, i, b): (i, b) for i, b in enumerate(batches)}
        for done, future in enumerate(as_completed(futures), start=1):
            index, batch = futures[future]
            try:
                _, batch, results, usage = future.result()
                for key in totals:
                    totals[key] += usage[key]

                by_id = {r.get("id"): r for r in results if isinstance(r, dict)}
                for idx, article in enumerate(batch):
                    verdict = by_id.get(idx)
                    if verdict is None:
                        continue
                    record = dict(article)
                    record.update({
                        "company": verdict.get("company") or "Not named",
                        "event_type": verdict.get("event_type") or article["event_guess"],
                        "location": verdict.get("location") or ", ".join(article["regions"]),
                        "foreign_parent": bool(verdict.get("foreign_parent")),
                        "investment_inr_crore": verdict.get("investment_inr_crore"),
                        "jobs": verdict.get("jobs"),
                        "tax_services": verdict.get("tax_services") or [],
                        "pitch_note": verdict.get("pitch_note") or "",
                        "evidence": verdict.get("evidence") or "",
                        "confidence": int(verdict.get("confidence") or 0),
                        "score": int(verdict.get("priority_score") or 0),
                        "reject_reason": verdict.get("reject_reason") or "",
                        "engine": "AI",
                    })
                    (leads if verdict.get("relevant") else rejected).append(record)
            except Exception as exc:
                errors.append(f"Batch {index + 1}: {type(exc).__name__}: {exc}"[:220])

            if progress_callback:
                progress_callback(done, len(batches))

    telemetry = {
        "batches": len(batches), "errors": errors, "model": model, "effort": effort,
        **totals,
        "estimated_cost_usd": estimate_cost(
            model, totals["input_tokens"], totals["output_tokens"]),
    }
    return leads, rejected, telemetry


# --------------------------------------------------------------------
# Gemini engine (Google free tier)
# --------------------------------------------------------------------

# Gemini's structured output accepts a narrower schema dialect than Claude:
# union types like ["string", "null"] are rejected. Every field is therefore a
# plain type, with "" and 0 standing in for "not stated", normalised below.
GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "reject_reason": {"type": "string"},
                    "company": {"type": "string"},
                    "event_type": {"type": "string", "enum": EVENT_TYPES},
                    "location": {"type": "string"},
                    "foreign_parent": {"type": "boolean"},
                    "investment_inr_crore": {"type": "number"},
                    "jobs": {"type": "integer"},
                    "tax_services": {"type": "array",
                                     "items": {"type": "string", "enum": SERVICE_LINES}},
                    "pitch_note": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "integer"},
                    "priority_score": {"type": "integer"},
                },
                "required": [
                    "id", "relevant", "reject_reason", "company", "event_type",
                    "location", "foreign_parent", "investment_inr_crore", "jobs",
                    "tax_services", "pitch_note", "evidence", "confidence",
                    "priority_score",
                ],
            },
        }
    },
    "required": ["results"],
}

GEMINI_SYSTEM_SUFFIX = """

OUTPUT ENCODING: this interface cannot represent null. Where a value is not \
stated in the article, use an empty string "" for text fields and 0 for \
investment_inr_crore and jobs. Never invent a figure to avoid writing 0."""


def get_gemini_key():
    """Resolve the Gemini key from Streamlit secrets first, then env."""
    try:
        import streamlit as st
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if name in st.secrets:
                return str(st.secrets[name]).strip()
    except Exception:
        pass
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def gemini_available(api_key=None):
    key = api_key if api_key is not None else get_gemini_key()
    if not key:
        return False
    try:
        import google.genai  # noqa: F401
        return True
    except ImportError:
        return False


def _clean_gemini_value(value, numeric=False):
    """Turn Gemini's ""/0 placeholders back into None."""
    if numeric:
        return value if value else None
    return value if value not in ("", None) else None


def _gemini_batch(client, batch, model):
    """One Gemini call, retrying on the free tier's rate limit."""
    import time as _time
    from google.genai import errors, types

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + GEMINI_SYSTEM_SUFFIX,
        response_mime_type="application/json",
        response_json_schema=GEMINI_SCHEMA,
        temperature=0,
        max_output_tokens=8192,
        # Thinking is unnecessary for a rubric-driven classification and eats
        # into the free tier's per-minute allowance.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    last_error = None
    for attempt in range(GEMINI_RETRIES):
        try:
            response = client.models.generate_content(
                model=model,
                contents=_format_batch(batch),
                config=config,
            )
            payload = json.loads(response.text)
            usage = response.usage_metadata
            return payload.get("results", []), {
                "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                "cache_read": getattr(usage, "cached_content_token_count", 0) or 0,
            }
        except errors.ClientError as exc:
            # 429 = free-tier rate limit. Back off and try again; anything
            # else (bad key, bad model name) should surface immediately.
            if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc).upper():
                raise
            last_error = exc
            _time.sleep(2 ** attempt * 5)
        except json.JSONDecodeError as exc:
            last_error = exc
            _time.sleep(2)

    raise RuntimeError(f"Gemini rate limit or bad response after "
                       f"{GEMINI_RETRIES} attempts: {last_error}")


def analyse_with_gemini(candidates, api_key, model=DEFAULT_GEMINI_MODEL,
                        progress_callback=None):
    """Same contract as analyse_with_ai, on Google's free tier."""
    from google import genai

    client = genai.Client(api_key=api_key)
    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]
    leads, rejected, errors_seen = [], [], []
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0}

    def run(index, batch):
        results, usage = _gemini_batch(client, batch, model)
        return index, batch, results, usage

    with ThreadPoolExecutor(max_workers=GEMINI_WORKERS) as pool:
        futures = {pool.submit(run, i, b): (i, b) for i, b in enumerate(batches)}
        for done, future in enumerate(as_completed(futures), start=1):
            index, batch = futures[future]
            try:
                _, batch, results, usage = future.result()
                for key in totals:
                    totals[key] += usage[key]

                by_id = {r.get("id"): r for r in results if isinstance(r, dict)}
                for idx, article in enumerate(batch):
                    verdict = by_id.get(idx)
                    if verdict is None:
                        continue
                    record = dict(article)
                    record.update({
                        "company": _clean_gemini_value(verdict.get("company")) or "Not named",
                        "event_type": _clean_gemini_value(verdict.get("event_type"))
                                      or article["event_guess"],
                        "location": _clean_gemini_value(verdict.get("location"))
                                    or ", ".join(article["regions"]),
                        "foreign_parent": bool(verdict.get("foreign_parent")),
                        "investment_inr_crore": _clean_gemini_value(
                            verdict.get("investment_inr_crore"), numeric=True),
                        "jobs": _clean_gemini_value(verdict.get("jobs"), numeric=True),
                        "tax_services": verdict.get("tax_services") or [],
                        "pitch_note": _clean_gemini_value(verdict.get("pitch_note")) or "",
                        "evidence": _clean_gemini_value(verdict.get("evidence")) or "",
                        "confidence": int(verdict.get("confidence") or 0),
                        "score": int(verdict.get("priority_score") or 0),
                        "reject_reason": _clean_gemini_value(verdict.get("reject_reason")) or "",
                        "engine": "Gemini",
                    })
                    (leads if verdict.get("relevant") else rejected).append(record)
            except Exception as exc:
                errors_seen.append(f"Batch {index + 1}: {type(exc).__name__}: {exc}"[:220])

            if progress_callback:
                progress_callback(done, len(batches))

    telemetry = {
        "batches": len(batches), "errors": errors_seen, "model": model,
        "effort": "n/a", **totals,
        "estimated_cost_usd": 0.0,      # free tier
    }
    return leads, rejected, telemetry


# --------------------------------------------------------------------
# Keyword fallback - precision first
# --------------------------------------------------------------------

_FALLBACK_SERVICES = {
    "New GCC / Capability Centre": ["Transfer Pricing", "Permanent Establishment Risk",
                                    "Corporate Tax"],
    "Foreign Subsidiary / India Entry": ["Entity Setup / Incorporation",
                                         "International Tax / Treaty", "FEMA / Regulatory"],
    "New Entity / Company Incorporation": ["Entity Setup / Incorporation", "Corporate Tax"],
    "Office / Campus Setup": ["Entity Setup / Incorporation", "Corporate Tax"],
    "Manufacturing Plant / Project": ["State Incentives", "Corporate Tax", "Withholding Tax"],
    "R&D / Innovation Centre": ["Transfer Pricing", "Corporate Tax"],
    "Data Centre": ["State Incentives", "Corporate Tax", "Withholding Tax"],
    "Major Investment / Capex": ["State Incentives", "Corporate Tax"],
    "M&A / JV": ["M&A / Deal Tax", "International Tax / Treaty", "FEMA / Regulatory"],
    "Expansion of Existing Operations": ["Transfer Pricing", "Corporate Tax"],
}


def analyse_with_keywords(candidates):
    """Offline fallback.

    Everything reaching this point already cleared the lead gate in prefilter,
    so this mostly scores and describes. It still rejects anything whose
    locality could not be confirmed from the headline or a specific place name.
    """
    leads, rejected = [], []

    for article in candidates:
        title, summary = article["title"], article["summary"]
        text = f"{title}. {summary}"
        lower = text.lower()

        record = dict(article)
        record["engine"] = "Keyword"

        company = extract_company(title)
        event = article["event_guess"]
        investment = article["investment_guess"]
        foreign = any(marker in lower for marker in FOREIGN_MARKERS)

        # Confirm the event is actually sited in the region: a specific city or
        # district must appear, not merely the state name in passing.
        specific_places = [
            place for terms in REGION_TERMS.values() for place in terms
            if place in lower and place not in ("andhra pradesh", "telangana")
        ]
        if not specific_places and not detect_regions(title):
            record.update({
                "reject_reason": "Region mentioned but no specific AP/Telangana location for the event",
                "score": 0, "confidence": 0, "company": company or "", "event_type": event,
                "location": "", "foreign_parent": foreign, "investment_inr_crore": investment,
                "jobs": None, "tax_services": [], "pitch_note": "", "evidence": "",
            })
            rejected.append(record)
            continue

        if not company:
            record.update({
                "reject_reason": "No company name could be read from the headline",
                "score": 0, "confidence": 0, "company": "", "event_type": event,
                "location": "", "foreign_parent": foreign, "investment_inr_crore": investment,
                "jobs": None, "tax_services": [], "pitch_note": "", "evidence": "",
            })
            rejected.append(record)
            continue

        score = min(article["signal"], 100)

        jobs = None
        jobs_match = re.search(
            r"\b([1-9]\d{2,}|\d{1,3},\d{3})\s+(?:jobs|employees|professionals|people)\b", lower)
        if jobs_match:
            try:
                jobs = int(jobs_match.group(1).replace(",", ""))
            except ValueError:
                pass

        location = ", ".join(dict.fromkeys(p.title() for p in specific_places[:2])) \
            or ", ".join(article["regions"])

        money = f" Stated investment about Rs {investment:,.0f} crore." if investment else ""
        origin = "Foreign-parent entity - treaty, PE and transfer pricing exposure. " \
            if foreign else ""
        record.update({
            "company": company,
            "event_type": event,
            "location": location,
            "foreign_parent": foreign,
            "investment_inr_crore": investment,
            "jobs": jobs,
            "tax_services": _FALLBACK_SERVICES.get(event, ["Corporate Tax"]),
            "pitch_note": f"{company}: {event.lower()} in {location}.{money} "
                          f"{origin}Keyword match - confirm the story before calling.",
            "evidence": "",
            "confidence": 40,
            "score": score,
            "reject_reason": "",
        })
        leads.append(record)

    telemetry = {"batches": 0, "errors": [], "model": "keyword-fallback", "effort": "n/a",
                 "input_tokens": 0, "output_tokens": 0, "cache_read": 0,
                 "estimated_cost_usd": 0.0}
    return leads, rejected, telemetry


def merge_duplicate_leads(leads):
    """Collapse the same company+event reported by several publishers.

    Title-level dedup cannot catch this: six outlets write six different
    headlines about one Charles Schwab announcement. Grouping on the company
    and event type instead gives the partner one row per opportunity, with
    every source that carried it listed underneath.
    """
    grouped = {}
    resolved = {}          # company key -> the group key it was folded into

    def resolve(company_key):
        """Fold near-identical company names together.

        "Reliance", "Reliance Industries" and "Reliance Proposes" are one
        prospect. Exact-key grouping leaves them as three rows, so treat a
        name that is a prefix of an existing one as the same company.
        """
        if company_key in resolved:
            return resolved[company_key]
        for known in resolved:
            if len(known) >= 5 and len(company_key) >= 5 and (
                known.startswith(company_key) or company_key.startswith(known)
            ):
                resolved[company_key] = resolved[known]
                return resolved[known]
        resolved[company_key] = company_key
        return company_key

    for lead in leads:
        # Group on the company alone, not company+event: a partner makes one
        # call per company, and the same announcement is often filed under two
        # different event types by different publishers.
        company_key = re.sub(r"[^a-z0-9]+", "", (lead.get("company") or "").lower())[:32]
        key = resolve(company_key) if company_key else lead["url"]

        existing = grouped.get(key)
        if existing is None:
            lead = dict(lead)
            lead["also_reported_by"] = []
            lead["coverage_count"] = 1
            grouped[key] = lead
            continue

        existing["coverage_count"] += 1
        if lead["source"] != existing["source"]:
            existing["also_reported_by"].append({
                "source": lead["source"], "url": lead["url"], "title": lead["title"],
            })

        # Keep the richest version: prefer the higher score, then fill in any
        # figure the winning article happened not to mention.
        if lead.get("score", 0) > existing.get("score", 0):
            carried = {k: existing[k] for k in ("also_reported_by", "coverage_count")}
            existing.clear()
            existing.update(lead)
            existing.update(carried)
        for field in ("investment_inr_crore", "jobs"):
            if existing.get(field) is None and lead.get(field) is not None:
                existing[field] = lead[field]
        if lead.get("foreign_parent"):
            existing["foreign_parent"] = True

    merged = list(grouped.values())
    merged.sort(key=lambda l: l.get("score", 0), reverse=True)
    return merged


def priority_label(score):
    if score >= 80:
        return "Very High"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"
