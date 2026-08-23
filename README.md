[README.md](https://github.com/user-attachments/files/31353887/README.md)
# Big 4 Tax Pitch Opportunities — AP / Telangana

Lead generation for a **direct tax** practice. Scans 33 Indian business news
feeds and uses Claude to find companies worth pitching in **Telangana and
Andhra Pradesh** — GCC setups, foreign subsidiaries, new entities, plants,
data centres and heavy capex.

A result only appears if it gives you (a) a named company to call and (b) a
concrete event landing in one of those two states.

## Run it locally

First time only — create a virtual environment and install dependencies:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Then start the app (this is the command to reuse every time):

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

It opens at <http://localhost:8501>. On macOS or Linux the interpreter path is
`.venv/bin/python` instead.

## Switch on AI analysis

Without an API key the app runs a keyword scorer and labels itself
**Keyword mode**. The gate above keeps that mode usable, but it still cannot
read meaning: it cannot tell "Naidu promises data centres" from "Google builds
a data centre", and it reads company names off headline word order. Treat
keyword-mode results as a shortlist to verify, not a call list.

To enable real analysis, copy the template and add your key:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then paste your key from <https://console.anthropic.com/settings/keys> into
that file. Restart the app and the sidebar will show **Claude connected**.

`secrets.toml` is gitignored. An `ANTHROPIC_API_KEY` environment variable
works too, and is what Streamlit Community Cloud expects (set it under
*App settings → Secrets*).

## How it decides what to show

Three stages, with the drop counts for each shown on the **Sources** tab:

1. **Fetch** — all 33 feeds in parallel, ~2,500 articles.
2. **Lead gate** — an article survives only if it clears every test:
   - mentions a real AP or Telangana location
   - is not sport, crime, accidents, weather, politics or market commentary
   - is not a round-up, listicle or weekly wrap
   - contains a *concrete* event (a centre opened, an entity incorporated,
     a plant commissioned, a stated investment figure) — not vague words
     like "investment" on their own
   - **names an actual company**. Government announcements with no private
     investor are dropped; so are politicians' names and place names that
     look like companies in title-case headlines.
3. **Analyse** — Claude reads the survivors and applies the real test: is
   this a company you could call this week about something landing in one of
   those two states? It extracts the company, investment figure, headcount,
   whether the parent is foreign, the service lines and a confidence score.

Typical funnel: **~2,500 articles → ~40 qualified → ~18 leads.**

Leads are then **merged by company**, so one announcement carried by eight
publishers is one row with the other seven listed as "also reported by".

Anything rejected appears on the **Filtered out** tab with its reason, so you
can check whether the filter is too strict or too loose.

Every AI result carries an `evidence` quote pulled from the source text. If a
card makes a claim, that quote is where it came from.

## Event types tracked

New GCC / Capability Centre · Foreign Subsidiary / India Entry · New Entity /
Company Incorporation · Office / Campus Setup · Manufacturing Plant / Project ·
Data Centre · R&D / Innovation Centre · Major Investment / Capex · M&A / JV ·
Expansion of Existing Operations

Hiring-only stories and government policy news are deliberately excluded —
neither gives you a client to pitch.

## Sidebar filters

- **Minimum priority score** — commercial value of the opportunity.
- **Minimum confidence** (AI mode only) — hides results the analysis was
  unsure about.
- **Minimum investment (Rs crore)** — for chasing heavy capex only.
- **Foreign-parent entities only** — subsidiaries and India-entry cases,
  where treaty, PE and transfer pricing work concentrates.

## Deploy on Streamlit Community Cloud

GitHub stores the code; Streamlit Community Cloud runs it, free.

1. Push this repo to GitHub (it must be a repo you own).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. **New app** → pick this repository, branch `main`, main file `app.py`.
4. Open **Advanced settings → Secrets** and paste:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

5. Deploy. The app rebuilds automatically on every push to `main`.

Set the key in step 4, never in a committed file — `.streamlit/secrets.toml`
is gitignored precisely so a key cannot reach GitHub. If a key is ever
committed by accident, revoke it at
<https://console.anthropic.com/settings/keys> and issue a new one.

Note that a Community Cloud app is **publicly viewable** by default. Anyone
with the URL can press *Run live scan* and spend against your API key. Keep
the repo private and restrict app viewers if that matters.

## Cost

Roughly $0.05–0.15 per scan at 140 articles on `claude-opus-5`. The Sources
tab reports exact token usage and estimated cost after each run. Lower it by
reducing *Max articles to analyse* or setting *Analysis depth* to `low`.

## Files

| File | Purpose |
|---|---|
| `app.py` | UI, tabs, filters, card rendering |
| `feeds.py` | Feed registry, parallel fetching, date parsing and formatting |
| `analysis.py` | Region gate, ranking, Claude analysis, keyword fallback |
| `theme.py` | ChatGPT-style CSS |

## Adding a feed

Add a line to `FEEDS` in [`feeds.py`](feeds.py):

```python
"Publisher - Section": ("https://example.com/rss", "National business"),
```

The category is the grouping heading on the Sources tab. Broken feeds show up
there as red rows with the HTTP error, so a dead URL is visible rather than
silent.
