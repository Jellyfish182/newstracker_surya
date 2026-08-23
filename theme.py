"""ChatGPT-style visual theme.

Neutral greys, one green accent, generous whitespace, hairline borders and
almost no shadow. Every colour is a token on :root so the palette can be
retuned in one place.
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --bg:            #ffffff;
    --bg-subtle:     #f7f7f8;
    --bg-sunken:     #f0f0f1;
    --surface:       #ffffff;
    --border:        #e5e5e5;
    --border-strong: #d4d4d4;

    --text:          #0d0d0d;
    --text-muted:    #6e6e80;
    --text-faint:    #9a9aa8;

    --accent:        #10a37f;
    --accent-hover:  #0e8f6f;
    --accent-soft:   #e7f6f1;
    --accent-border: #a7dcca;

    --amber:         #b45309;
    --amber-soft:    #fef3e2;
    --amber-border:  #f5d0a9;

    --red:           #b42318;
    --red-soft:      #fef3f2;
    --red-border:    #fecdc9;

    --blue:          #175cd3;
    --blue-soft:     #eff4ff;
    --blue-border:   #b2ccff;

    --radius:        12px;
    --radius-lg:     16px;
    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
            Helvetica, Arial, sans-serif;
}

/* ---------- Base ---------- */

.stApp {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
}

.block-container {
    max-width: 1180px;
    padding-top: 2rem;
    padding-bottom: 4rem;
}

h1, h2, h3, h4 {
    font-family: var(--font);
    color: var(--text);
    letter-spacing: -0.02em;
    font-weight: 600 !important;
}

h1 { font-size: 1.9rem !important; }
h2 { font-size: 1.35rem !important; }
h3 { font-size: 1.08rem !important; }

p, span, div, label { font-family: var(--font); }

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 1.75rem 0 !important;
}

/* Hide Streamlit chrome selectively.

   The button that reopens a collapsed sidebar lives INSIDE the header toolbar,
   so neither the header nor the toolbar may be hidden: `visibility: hidden` on
   the header, or `display: none` on the toolbar, leaves that button rendered
   but zero-sized, and the user is stranded with no way back to the controls.
   Hide the individual pieces instead. */
footer { visibility: hidden; }
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenuButton"] { display: none !important; }
[data-testid="stHeader"] { background: transparent; visibility: visible; }
[data-testid="stToolbar"] { visibility: visible; }

[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapseButton"] {
    visibility: visible !important;
    opacity: 1 !important;
    z-index: 1000000;
}

[data-testid="stExpandSidebarButton"] button,
[data-testid="stSidebarCollapseButton"] button {
    visibility: visible !important;
    opacity: 1 !important;
    color: var(--text-muted) !important;
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    width: auto !important;
    box-shadow: none !important;
}

[data-testid="stExpandSidebarButton"] button:hover,
[data-testid="stSidebarCollapseButton"] button:hover {
    background: var(--bg-subtle) !important;
    color: var(--text) !important;
    opacity: 1 !important;
}

/* ---------- Sidebar ---------- */

[data-testid="stSidebar"] {
    background: var(--bg-subtle);
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    font-size: 0.75rem !important;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--text-faint);
    font-weight: 600 !important;
    margin-bottom: 0.6rem !important;
}

/* ---------- Buttons ---------- */

.stButton > button {
    border-radius: 999px !important;
    border: 1px solid var(--text) !important;
    background: var(--text) !important;
    color: #ffffff !important;
    padding: 0.55rem 1.3rem !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
    box-shadow: none !important;
    transition: opacity 0.15s ease;
    width: 100%;
}

.stButton > button:hover {
    opacity: 0.85;
    border-color: var(--text) !important;
    background: var(--text) !important;
    color: #ffffff !important;
}

.stButton > button:focus:not(:active) {
    border-color: var(--text) !important;
    color: #ffffff !important;
}

.stDownloadButton > button {
    border-radius: 999px !important;
    border: 1px solid var(--border-strong) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    font-weight: 500 !important;
    font-size: 0.88rem !important;
    padding: 0.5rem 1.15rem !important;
    box-shadow: none !important;
}

.stDownloadButton > button:hover {
    background: var(--bg-subtle) !important;
    border-color: var(--text-faint) !important;
}

/* ---------- Inputs ---------- */

[data-baseweb="input"], [data-baseweb="select"] > div {
    border-radius: 10px !important;
    border-color: var(--border-strong) !important;
}

[data-baseweb="tag"] {
    background: var(--bg-sunken) !important;
    color: var(--text) !important;
    border-radius: 6px !important;
}

/* ---------- Tabs ---------- */

.stTabs [data-baseweb="tab-list"] {
    gap: 0.35rem;
    border-bottom: 1px solid var(--border);
    background: transparent;
}

.stTabs [data-baseweb="tab"] {
    height: 42px;
    background: transparent;
    border-radius: 8px 8px 0 0;
    padding: 0 0.95rem;
    font-size: 0.92rem;
    font-weight: 500;
    color: var(--text-muted);
}

.stTabs [aria-selected="true"] {
    background: transparent;
    color: var(--text) !important;
    border-bottom: 2px solid var(--text);
}

.stTabs [data-baseweb="tab-highlight"] { background: transparent; }

/* ---------- Metrics ---------- */

[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.95rem 1.1rem;
}

[data-testid="stMetricLabel"] {
    color: var(--text-muted);
    font-size: 0.8rem !important;
    font-weight: 500;
}

[data-testid="stMetricValue"] {
    color: var(--text);
    font-weight: 600;
    font-size: 1.45rem !important;
}

/* ---------- Hero ---------- */

.hero {
    padding: 0.5rem 0 1.5rem 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.75rem;
}

.hero-title {
    font-size: 2rem;
    font-weight: 600;
    letter-spacing: -0.03em;
    color: var(--text);
    margin: 0 0 0.4rem 0;
}

.hero-sub {
    color: var(--text-muted);
    font-size: 0.98rem;
    line-height: 1.6;
    max-width: 760px;
    margin: 0;
}

.hero-meta {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 1rem;
    align-items: center;
}

/* ---------- Pills ---------- */

.pill {
    display: inline-flex;
    align-items: center;
    gap: 0.32rem;
    padding: 0.24rem 0.66rem;
    border-radius: 999px;
    font-size: 0.775rem;
    font-weight: 500;
    border: 1px solid var(--border);
    background: var(--bg-subtle);
    color: var(--text-muted);
    white-space: nowrap;
}

.pill-green  { background: var(--accent-soft); border-color: var(--accent-border); color: #0b7a5e; }
.pill-amber  { background: var(--amber-soft);  border-color: var(--amber-border);  color: var(--amber); }
.pill-red    { background: var(--red-soft);    border-color: var(--red-border);    color: var(--red); }
.pill-blue   { background: var(--blue-soft);   border-color: var(--blue-border);   color: var(--blue); }

/* ---------- Opportunity card ---------- */

.day-heading {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: var(--text-faint);
    margin: 1.9rem 0 0.7rem 0;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid var(--border);
}

.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.15rem 1.3rem;
    margin-bottom: 0.75rem;
    transition: border-color 0.15s ease;
}

.card:hover { border-color: var(--border-strong); }

.card-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    margin-bottom: 0.5rem;
}

.card-company {
    font-size: 1.06rem;
    font-weight: 600;
    color: var(--text);
    letter-spacing: -0.015em;
    line-height: 1.35;
}

.card-score {
    flex-shrink: 0;
    text-align: right;
}

.score-number {
    font-size: 1.4rem;
    font-weight: 600;
    color: var(--text);
    line-height: 1;
}

.score-caption {
    font-size: 0.68rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-top: 0.15rem;
}

.card-pitch {
    color: #3c3c46;
    font-size: 0.925rem;
    line-height: 1.6;
    margin: 0.55rem 0 0.75rem 0;
}

.card-evidence {
    border-left: 2px solid var(--border-strong);
    padding: 0.15rem 0 0.15rem 0.75rem;
    margin: 0.6rem 0 0.8rem 0;
    color: var(--text-muted);
    font-size: 0.855rem;
    font-style: italic;
    line-height: 1.55;
}

.card-coverage {
    margin-top: 0.6rem;
    font-size: 0.79rem;
    color: var(--text-faint);
    line-height: 1.5;
}

.card-coverage a { color: var(--text-muted); }
.card-coverage a:hover { color: var(--accent); }

.card-meta {
    display: flex;
    gap: 0.45rem;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 0.7rem;
}

.card-foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    margin-top: 0.85rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
    font-size: 0.8rem;
    color: var(--text-faint);
}

.card-date { display: flex; align-items: center; gap: 0.4rem; }
.card-date strong { color: var(--text-muted); font-weight: 500; }
.card-dot { color: var(--border-strong); }

.card-link {
    color: var(--text-muted);
    font-weight: 500;
    white-space: nowrap;
}
.card-link:hover { color: var(--accent); }

/* ---------- Source rows ---------- */

.src-row {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.72rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 0.4rem;
    background: var(--surface);
}

.src-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.src-dot-ok    { background: var(--accent); }
.src-dot-empty { background: #d4a017; }
.src-dot-fail  { background: #d92d20; }

.src-main { flex: 1; min-width: 0; }

.src-name {
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--text);
    margin-bottom: 0.12rem;
}

.src-url {
    font-size: 0.755rem;
    color: var(--text-faint);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.src-stats {
    display: flex;
    gap: 1.3rem;
    flex-shrink: 0;
    text-align: right;
}

.src-stat-val {
    font-size: 0.92rem;
    font-weight: 600;
    color: var(--text);
    line-height: 1.2;
}

.src-stat-lbl {
    font-size: 0.66rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.src-error {
    font-size: 0.76rem;
    color: var(--red);
    margin-top: 0.2rem;
}

/* ---------- Misc ---------- */

.note {
    background: var(--bg-subtle);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.85rem 1.05rem;
    font-size: 0.875rem;
    color: var(--text-muted);
    line-height: 1.6;
}

.empty-state {
    text-align: center;
    padding: 3.5rem 1rem;
    color: var(--text-muted);
}

.empty-state-title {
    font-size: 1.08rem;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 0.45rem;
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--border);
    border-radius: var(--radius);
}

.stAlert { border-radius: var(--radius); }

[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--surface);
}

.stProgress > div > div > div > div { background-color: var(--accent); }
</style>
"""


def priority_pill_class(label):
    return {
        "Very High": "pill-red",
        "High": "pill-amber",
        "Medium": "pill-blue",
    }.get(label, "pill")
