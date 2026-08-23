"""Big 4 Tax Pitch Opportunities - AP / Telangana.

Scans Indian business RSS feeds, then has Claude read each Andhra Pradesh /
Telangana story and judge whether it is a genuine, actionable tax advisory
opportunity. Falls back to keyword matching when no API key is configured.
"""

import html
import time
from datetime import datetime

import pandas as pd
import streamlit as st

import analysis
import feeds
import theme

st.set_page_config(
    page_title="Big 4 Tax Pitch Opportunities",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(theme.CSS, unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def cached_feed_fetch():
    """Feed results, reused for 10 minutes.

    Streamlit Cloud runs in a US datacentre fetching Indian news sites, so
    this stage is far slower there than locally. News does not change minute
    to minute, so a repeat scan should not pay for it twice.
    """
    return feeds.fetch_all_feeds()


def esc(value):
    """Escape user/model text before it goes into an HTML block."""
    return html.escape(str(value or ""))


# =====================================================================
# Scan pipeline
# =====================================================================

def run_scan(provider, api_key, model, effort, max_candidates, fresh_feeds=False):
    """Fetch -> prefilter -> analyse. Returns a result dict held in session."""
    started = time.perf_counter()
    progress = st.progress(0.0, text="Connecting to feeds...")

    if fresh_feeds:
        cached_feed_fetch.clear()

    progress.progress(0.2, text="Reading feeds...")
    feed_results = cached_feed_fetch()
    progress.progress(0.45, text=f"Read {len(feed_results)} feeds")

    progress.progress(0.5, text="Filtering for Andhra Pradesh and Telangana...")
    candidates, prefilter_stats = analysis.prefilter(feed_results, max_candidates)

    if not candidates:
        progress.empty()
        return {
            "feed_results": feed_results, "prefilter": prefilter_stats,
            "opportunities": [], "rejected": [], "telemetry": {},
            "engine": provider,
            "scanned_at": datetime.now(feeds.IST),
        }

    label = {"gemini": "Gemini", "claude": "Claude"}.get(provider, "")

    def on_batch(done, total):
        elapsed = int(time.perf_counter() - started)
        progress.progress(
            0.5 + (done / total) * 0.5,
            text=f"{label} is reading articles... batch {done}/{total}  ·  {elapsed}s",
        )

    if provider in ("gemini", "claude"):
        total_batches = -(-len(candidates) // analysis.BATCH_SIZE)
        progress.progress(
            0.5,
            text=f"{label} is reading {len(candidates)} articles "
                 f"in {total_batches} batches...",
        )

    if provider == "gemini":
        opportunities, rejected, telemetry = analysis.analyse_with_gemini(
            candidates, api_key=api_key, model=model, progress_callback=on_batch,
        )
    elif provider == "claude":
        opportunities, rejected, telemetry = analysis.analyse_with_ai(
            candidates, api_key=api_key, model=model, effort=effort,
            progress_callback=on_batch,
        )
    else:
        progress.progress(0.75, text="Running keyword analysis...")
        opportunities, rejected, telemetry = analysis.analyse_with_keywords(candidates)

    opportunities = analysis.merge_duplicate_leads(opportunities)

    # Attribute confirmed opportunities back to their feeds for the Sources tab.
    kept_by_source = {}
    for opp in opportunities:
        kept_by_source[opp["source"]] = kept_by_source.get(opp["source"], 0) + 1
    analysed_by_source = {}
    for cand in candidates:
        analysed_by_source[cand["source"]] = analysed_by_source.get(cand["source"], 0) + 1
    for feed in feed_results:
        feed.kept_count = kept_by_source.get(feed.name, 0)
        feed.analysed_count = analysed_by_source.get(feed.name, 0)

    opportunities.sort(key=lambda o: o["score"], reverse=True)
    progress.empty()

    return {
        "feed_results": feed_results,
        "prefilter": prefilter_stats,
        "opportunities": opportunities,
        "rejected": rejected,
        "telemetry": telemetry,
        "engine": provider,
        "scanned_at": datetime.now(feeds.IST),
        "duration_s": round(time.perf_counter() - started, 1),
    }


def to_dataframe(rows):
    """Flatten opportunity records into an export-friendly table."""
    records = []
    for row in rows:
        published = row.get("published")
        records.append({
            "Published": feeds.format_absolute(published),
            "Published (ISO)": published.isoformat() if published else "",
            "Age": feeds.format_relative(published),
            "Company": row.get("company", ""),
            "Event Type": row.get("event_type", ""),
            "Location": row.get("location", ""),
            "Foreign Parent": "Yes" if row.get("foreign_parent") else "No",
            "Investment (INR cr)": row.get("investment_inr_crore"),
            "Jobs": row.get("jobs"),
            "Tax Services": ", ".join(row.get("tax_services", [])),
            "Pitch Note": row.get("pitch_note", ""),
            "Evidence": row.get("evidence", ""),
            "Priority": analysis.priority_label(row.get("score", 0)),
            "Score": row.get("score", 0),
            "Confidence": row.get("confidence", 0),
            "Source": row.get("source", ""),
            "Also reported by": ", ".join(
                o["source"] for o in row.get("also_reported_by", [])),
            "Headline": row.get("title", ""),
            "URL": row.get("url", ""),
        })
    return pd.DataFrame(records)


# =====================================================================
# Sidebar
# =====================================================================

claude_key = analysis.get_api_key()
gemini_key = analysis.get_gemini_key()
claude_ready = analysis.ai_available(claude_key)
gemini_ready = analysis.gemini_available(gemini_key)

with st.sidebar:
    st.markdown("### Analysis engine")

    # Build the list of engines that are actually usable right now, so the
    # user is never offered something that will fail on click.
    engines = []
    if gemini_ready:
        engines.append("Gemini (free)")
    if claude_ready:
        engines.append("Claude (paid)")
    engines.append("Keyword only")

    if len(engines) == 1:
        engine = "Keyword only"
        st.markdown('<span class="pill pill-amber">● Keyword mode</span>',
                    unsafe_allow_html=True)
        st.caption(
            "No API key found. Add `GEMINI_API_KEY` for the free Google tier, "
            "or `ANTHROPIC_API_KEY` for Claude, to switch on real analysis."
        )
    else:
        engine = st.radio("Engine", engines, index=0, label_visibility="collapsed")

    provider, model, effort = "keyword", "keyword-fallback", "low"

    if engine == "Gemini (free)":
        provider = "gemini"
        st.markdown('<span class="pill pill-green">● Gemini connected — free tier</span>',
                    unsafe_allow_html=True)
        model = st.selectbox(
            "Model", options=list(analysis.GEMINI_MODELS),
            index=list(analysis.GEMINI_MODELS).index(analysis.DEFAULT_GEMINI_MODEL),
            format_func=lambda m: analysis.GEMINI_MODELS[m]["label"],
        )
        st.caption(analysis.GEMINI_MODELS[model]["note"])

    elif engine == "Claude (paid)":
        provider = "claude"
        st.markdown('<span class="pill pill-green">● Claude connected</span>',
                    unsafe_allow_html=True)
        model = st.selectbox(
            "Model", options=list(analysis.MODELS),
            index=list(analysis.MODELS).index(analysis.DEFAULT_MODEL),
            format_func=lambda m: analysis.MODELS[m]["label"],
            help="Cheapest first. All three read the article properly - they "
                 "differ in how well they judge borderline cases.",
        )
        st.caption(analysis.MODELS[model]["note"])
        if analysis.MODELS[model]["supports_effort"]:
            effort = st.select_slider(
                "Analysis depth", options=["low", "medium", "high"], value="low",
                help="Lower depth is cheaper and faster.",
            )

    use_ai = provider != "keyword"

    st.markdown("### Scan settings")
    max_candidates = st.slider(
        "Max articles to analyse", 20, 200, 80, 10,
        help="Caps scan time. Best-scoring leads are kept first, so a lower "
             "number rarely loses anything worth calling.",
    )
    if use_ai:
        min_confidence = st.slider(
            "Minimum confidence", 0, 100, 50, 5,
            help="Hide results the analysis was not sure about.",
        )
    else:
        # Keyword matching reports a flat, uninformative confidence, so
        # filtering on it would only ever hide everything or nothing.
        min_confidence = 0
        st.caption("Confidence filtering is unavailable in keyword mode.")

    min_score = st.slider("Minimum priority score", 0, 100, 40, 5)

    st.markdown("### Lead filters")
    min_investment = st.number_input(
        "Minimum investment (Rs crore)", min_value=0, value=0, step=100,
        help="0 shows every lead, including those with no figure stated.",
    )
    foreign_only = st.checkbox(
        "Foreign-parent entities only",
        help="Subsidiaries and India-entry cases, where treaty, PE and "
             "transfer pricing work concentrates.",
    )

    st.markdown("### Run")
    fresh_feeds = st.checkbox(
        "Force fresh feed fetch", value=False,
        help="Feeds are reused for 10 minutes to keep scans fast. Tick this "
             "to pull them again immediately.",
    )
    scan_clicked = st.button("Run live scan", type="primary")

    if st.session_state.get("scan"):
        last = st.session_state["scan"]
        took = last.get("duration_s")
        st.caption(f"Last scan: {feeds.format_absolute(last['scanned_at'])}"
                   + (f" · took {took}s" if took else ""))


# =====================================================================
# Header
# =====================================================================

engine_pill = {
    "gemini": '<span class="pill pill-green">AI analysis - Gemini</span>',
    "claude": '<span class="pill pill-green">AI analysis - Claude</span>',
}.get(provider, '<span class="pill pill-amber">Keyword mode</span>')

st.markdown(
    f"""
<div class="hero">
  <div class="hero-title">Big 4 Tax Pitch Opportunities</div>
  <p class="hero-sub">
    Live scan of {len(feeds.FEEDS)} Indian business news feeds for Andhra Pradesh and
    Telangana. Every story is read and judged on what it actually says, not on keyword
    matches, then scored for tax advisory potential.
  </p>
  <div class="hero-meta">
    {engine_pill}
    <span class="pill">{len(feeds.FEEDS)} sources</span>
    <span class="pill">AP / Telangana</span>
    <span class="pill">Auditable output</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

if scan_clicked:
    active_key = gemini_key if provider == "gemini" else claude_key
    st.session_state["scan"] = run_scan(provider, active_key, model, effort,
                                        max_candidates, fresh_feeds)

scan = st.session_state.get("scan")

if not scan:
    st.markdown(
        """
<div class="empty-state">
  <div class="empty-state-title">No scan yet</div>
  <div>Press <strong>Run live scan</strong> in the sidebar to pull the latest stories.</div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.stop()


# =====================================================================
# Tabs
# =====================================================================

tab_opps, tab_sources, tab_rejected, tab_export = st.tabs(
    ["Opportunities", f"Sources ({len(scan['feed_results'])})", "Filtered out", "Export"]
)


# ---------------------------------------------------------------- Opportunities
with tab_opps:
    opportunities = [
        o for o in scan["opportunities"]
        if o.get("confidence", 0) >= min_confidence and o.get("score", 0) >= min_score
    ]

    if scan["telemetry"].get("errors"):
        with st.expander(f"{len(scan['telemetry']['errors'])} analysis batch(es) failed", expanded=False):
            for err in scan["telemetry"]["errors"]:
                st.write(f"- {err}")

    all_events = sorted({o["event_type"] for o in scan["opportunities"] if o.get("event_type")})
    all_services = sorted({s for o in scan["opportunities"] for s in o.get("tax_services", [])})

    fcol1, fcol2, fcol3 = st.columns([2, 2, 2])
    with fcol1:
        pick_events = st.multiselect("Event type", all_events, default=[])
    with fcol2:
        pick_services = st.multiselect("Tax service line", all_services, default=[])
    with fcol3:
        query = st.text_input("Search", placeholder="Company, location, keyword...")

    if foreign_only:
        opportunities = [o for o in opportunities if o.get("foreign_parent")]
    if min_investment:
        opportunities = [o for o in opportunities
                         if (o.get("investment_inr_crore") or 0) >= min_investment]
    if pick_events:
        opportunities = [o for o in opportunities if o["event_type"] in pick_events]
    if pick_services:
        opportunities = [o for o in opportunities
                         if any(s in pick_services for s in o.get("tax_services", []))]
    if query.strip():
        q = query.lower().strip()
        opportunities = [
            o for o in opportunities
            if q in f"{o.get('company','')} {o.get('location','')} {o.get('title','')} "
                    f"{o.get('pitch_note','')} {o.get('event_type','')}".lower()
        ]

    total_capex = sum(o["investment_inr_crore"] or 0 for o in opportunities)
    total_jobs = sum(o["jobs"] or 0 for o in opportunities)

    if total_capex >= 100_000:
        capex_display = f"{total_capex / 100_000:,.1f}L cr"
    elif total_capex >= 1_000:
        capex_display = f"{total_capex / 1_000:,.1f}K cr"
    elif total_capex:
        capex_display = f"{total_capex:,.0f} cr"
    else:
        capex_display = "-"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Found", len(opportunities))
    m2.metric("High priority",
              sum(1 for o in opportunities
                  if analysis.priority_label(o["score"]) in ("Very High", "High")))
    m3.metric("Capex (INR)", capex_display)
    m4.metric("Jobs", f"{total_jobs:,}" if total_jobs else "-")

    st.markdown("")

    if not opportunities:
        st.markdown(
            """
<div class="empty-state">
  <div class="empty-state-title">Nothing matched these filters</div>
  <div>Lower the confidence or score threshold in the sidebar, or clear the filters above.</div>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        # Group by publication day, newest day first.
        by_day = {}
        for opp in sorted(
            opportunities,
            key=lambda o: (o["published"] is not None, o["published"] or datetime.min.replace(tzinfo=feeds.IST)),
            reverse=True,
        ):
            by_day.setdefault(feeds.format_date_group(opp["published"]), []).append(opp)

        for day, items in by_day.items():
            st.markdown(f'<div class="day-heading">{esc(day)}</div>', unsafe_allow_html=True)

            for opp in sorted(items, key=lambda o: o["score"], reverse=True):
                label = analysis.priority_label(opp["score"])
                pills = [
                    f'<span class="pill {theme.priority_pill_class(label)}">{esc(label)}</span>',
                    f'<span class="pill">{esc(opp["event_type"])}</span>',
                    f'<span class="pill">{esc(opp["location"])}</span>',
                ]
                if opp.get("foreign_parent"):
                    pills.append('<span class="pill pill-red">Foreign parent</span>')
                if opp.get("investment_inr_crore"):
                    pills.append(
                        f'<span class="pill pill-green">Rs {opp["investment_inr_crore"]:,.0f} cr</span>'
                    )
                if opp.get("jobs"):
                    pills.append(f'<span class="pill pill-green">{opp["jobs"]:,} jobs</span>')
                for service in opp.get("tax_services", [])[:4]:
                    pills.append(f'<span class="pill pill-blue">{esc(service)}</span>')

                evidence = ""
                if opp.get("evidence"):
                    evidence = f'<div class="card-evidence">"{esc(opp["evidence"])}"</div>'

                coverage = ""
                if opp.get("coverage_count", 1) > 1:
                    others = opp.get("also_reported_by", [])
                    links = " · ".join(
                        f'<a href="{esc(o["url"])}" target="_blank">{esc(o["source"])}</a>'
                        for o in others[:6]
                    )
                    coverage = (
                        f'<div class="card-coverage">Also reported by {links}</div>'
                    )

                st.markdown(
                    f"""
<div class="card">
  <div class="card-top">
    <div class="card-company">{esc(opp["company"])}</div>
    <div class="card-score">
      <div class="score-number">{opp["score"]}</div>
      <div class="score-caption">{opp["confidence"]}% conf</div>
    </div>
  </div>
  <div class="card-pitch">{esc(opp["pitch_note"])}</div>
  {evidence}
  <div class="card-meta">{"".join(pills)}</div>
  {coverage}
  <div class="card-foot">
    <div class="card-date">
      <strong>{esc(feeds.format_absolute(opp["published"]))}</strong>
      <span class="card-dot">·</span>
      <span>{esc(feeds.format_relative(opp["published"]))}</span>
      <span class="card-dot">·</span>
      <span>{esc(opp["source"])}</span>
    </div>
    <a class="card-link" href="{esc(opp["url"])}" target="_blank">Read article →</a>
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------- Sources
with tab_sources:
    results = scan["feed_results"]
    stats = scan["prefilter"]

    ok = [r for r in results if r.status == "OK"]
    empty = [r for r in results if r.status == "Empty"]
    failed = [r for r in results if r.status == "Failed"]

    st.markdown("### Feeds consulted in this scan")
    st.markdown(
        f"""
<div class="note">
Every feed below was contacted during this scan. Articles flow through three stages:
<strong>fetched</strong> (items in the feed) →
<strong>analysed</strong> (items mentioning AP or Telangana, sent for reading) →
<strong>kept</strong> (items confirmed as genuine opportunities).
The gap between fetched and analysed is the regional filter; the gap between analysed and
kept is the analysis rejecting stories that do not hold up.
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Feeds responding", f"{len(ok)} / {len(results)}")
    s2.metric("Articles fetched", f"{stats['total_entries']:,}")
    s3.metric("Qualified leads", f"{stats['sent_for_analysis']:,}")
    s4.metric("Confirmed", f"{len(scan['opportunities']):,}")

    st.markdown("")
    st.markdown("**Why articles were dropped before analysis**")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Duplicates", f"{stats['duplicates']:,}")
    d2.metric("Off topic", f"{stats['off_topic']:,}")
    d3.metric("No real event", f"{stats['no_event']:,}")
    d4.metric("No company", f"{stats['no_company']:,}")
    d5.metric("Round-ups", f"{stats['roundup']:,}")
    st.caption(
        "Articles not counted above simply never mentioned Andhra Pradesh or "
        "Telangana. The remaining gap between qualified leads and confirmed is "
        "the analysis stage rejecting stories that did not hold up on reading."
    )

    if stats["dropped_by_cap"]:
        st.caption(
            f"{stats['dropped_by_cap']} regional matches were beyond the "
            f"{max_candidates}-article cap and were not analysed. Raise the cap in the sidebar to include them."
        )

    if failed:
        st.markdown("")
        st.warning(
            f"{len(failed)} feed(s) did not respond: "
            + ", ".join(r.name for r in failed)
            + ". Results below are drawn from the remaining sources."
        )

    st.markdown("")

    view = st.radio(
        "Show", ["All feeds", "Responding", "Failed or empty", "Feeds that produced results"],
        horizontal=True, label_visibility="collapsed",
    )

    if view == "Responding":
        shown = ok
    elif view == "Failed or empty":
        shown = failed + empty
    elif view == "Feeds that produced results":
        shown = [r for r in results if r.kept_count > 0]
    else:
        shown = results

    if not shown:
        st.info("No feeds in this view.")

    by_category = {}
    for feed in shown:
        by_category.setdefault(feed.category, []).append(feed)

    for category in sorted(by_category):
        group = sorted(by_category[category], key=lambda r: (-r.kept_count, r.name))
        st.markdown(f'<div class="day-heading">{esc(category)}</div>', unsafe_allow_html=True)

        for feed in group:
            dot = {"OK": "src-dot-ok", "Empty": "src-dot-empty"}.get(feed.status, "src-dot-fail")
            error_line = (
                f'<div class="src-error">{esc(feed.error)}</div>' if feed.error else ""
            )
            newest = (
                feeds.format_relative(feed.newest) if feed.newest else "no dates in feed"
            )

            st.markdown(
                f"""
<div class="src-row">
  <div class="src-dot {dot}"></div>
  <div class="src-main">
    <div class="src-name">{esc(feed.name)}</div>
    <div class="src-url">{esc(feed.url)}</div>
    {error_line}
  </div>
  <div class="src-stats">
    <div>
      <div class="src-stat-val">{feed.entry_count}</div>
      <div class="src-stat-lbl">Fetched</div>
    </div>
    <div>
      <div class="src-stat-val">{feed.analysed_count}</div>
      <div class="src-stat-lbl">Analysed</div>
    </div>
    <div>
      <div class="src-stat-val">{feed.kept_count}</div>
      <div class="src-stat-lbl">Kept</div>
    </div>
    <div>
      <div class="src-stat-val">{feed.elapsed_ms} ms</div>
      <div class="src-stat-lbl">{esc(newest)}</div>
    </div>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

    with st.expander("Full source table"):
        st.dataframe(
            pd.DataFrame([{
                "Feed": r.name,
                "Category": r.category,
                "Status": r.status,
                "Fetched": r.entry_count,
                "Analysed": r.analysed_count,
                "Kept": r.kept_count,
                "Response (ms)": r.elapsed_ms,
                "Newest item": feeds.format_absolute(r.newest) if r.newest else "",
                "Error": r.error,
                "URL": r.url,
            } for r in results]),
            width='stretch', hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("URL")},
        )

    telemetry = scan["telemetry"]
    if telemetry.get("batches"):
        st.markdown("")
        st.markdown("### Analysis run")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Model", telemetry["model"])
        t2.metric("Batches", telemetry["batches"])
        t3.metric("Tokens",
                  f"{telemetry['input_tokens'] + telemetry['output_tokens']:,}")
        t4.metric("Est. cost",
                  "Free" if telemetry["estimated_cost_usd"] == 0
                  else f"${telemetry['estimated_cost_usd']:.3f}")
        if telemetry.get("cache_read"):
            st.caption(f"{telemetry['cache_read']:,} input tokens served from prompt cache.")


# ---------------------------------------------------------------- Filtered out
with tab_rejected:
    rejected = scan["rejected"]
    st.markdown("### Articles the analysis rejected")
    st.markdown(
        """
<div class="note">
These stories mentioned Andhra Pradesh or Telangana but were judged not to be genuine
tax pitch opportunities. Reviewing this list is the fastest way to check whether the
analysis is being too strict or too loose.
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("")

    if not rejected:
        st.info("Nothing was rejected in this scan.")
    else:
        st.caption(f"{len(rejected)} article(s) filtered out.")
        st.dataframe(
            pd.DataFrame([{
                "Published": feeds.format_absolute(r["published"]),
                "Age": feeds.format_relative(r["published"]),
                "Headline": r["title"],
                "Why it was rejected": r.get("reject_reason", ""),
                "Source": r["source"],
                "URL": r["url"],
            } for r in rejected]),
            width='stretch', hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("URL")},
        )


# ---------------------------------------------------------------- Export
with tab_export:
    st.markdown("### Export")
    export_df = to_dataframe(scan["opportunities"])

    if export_df.empty:
        st.info("Nothing to export yet.")
    else:
        st.dataframe(
            export_df, width='stretch', hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100),
            },
        )
        stamp = scan["scanned_at"].strftime("%Y%m%d_%H%M")
        st.download_button(
            "Download CSV",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"tax_pitch_opportunities_{stamp}.csv",
            mime="text/csv",
        )
