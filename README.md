# SGBAU Tabulation Register → Excel & Dashboard

A Streamlit app for Sant Gadge Baba Amravati University (SGBAU) colleges that:

1. **Converts** the official Tabulation Register (TR) PDF into a clean, structured
   Excel workbook (`Marks Data`, `Subject Legend`, `Summary` sheets).
2. **Report Dashboard** — a single-page, printable analytics report (backlog
   analysis, pass/fail donut, subject-wise pass rates, toppers, key insights,
   recommended interventions) matching a supplied HTML template design exactly,
   generated live from the Excel and downloadable as a standalone `.html` file.
3. **Interactive Charts** — a supplementary Plotly-based page for ad-hoc,
   filterable deep-dives (heatmaps, histograms, demographic breakdowns).

Tested against a real 136-page / 391-student TR: **99.97% field-level accuracy**
against a manually verified reference conversion.

---

## Project structure

```
tr_dashboard_app/
├── app.py            # Streamlit app (3 pages: Convert, Report Dashboard, Interactive Charts)
├── tr_parser.py       # PDF parsing engine + Excel workbook builder
├── report.py           # Generates the single-page HTML analytics report (pure CSS, no JS)
├── requirements.txt   # Python dependencies
└── README.md          # this file
```

## Run it locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

---

## Deploy for free on Streamlit Community Cloud

Streamlit Community Cloud (share.streamlit.io) hosts public Streamlit apps for
free, directly from a GitHub repo.

### 1. Push this folder to GitHub

```bash
cd tr_dashboard_app
git init
git add .
git commit -m "Initial commit: SGBAU TR to Excel + Dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

(Create the empty repo on GitHub first at github.com/new — keep `app.py`,
`tr_parser.py` and `requirements.txt` in the repo root, or note the sub-path if not.)

### 2. Deploy on Streamlit Community Cloud

1. Go to **https://share.streamlit.io** and sign in with your GitHub account.
2. Click **"New app"**.
3. Select your repository, the branch (`main`), and set **Main file path** to
   `app.py` (or `tr_dashboard_app/app.py` if it's in a subfolder).
4. Click **"Deploy"**.

Streamlit Cloud will install `requirements.txt` automatically and give you a
public URL like `https://<your-app>.streamlit.app` within a couple of minutes.

### 3. Updating the app

Any `git push` to the connected branch automatically redeploys the app — no
manual redeploy step needed.

### Notes on the free tier

- Community Cloud apps sleep after a period of inactivity and wake up on the
  next visit (a few seconds' delay) — fine for occasional/departmental use.
- Resource limits (~1 GB RAM) are generous enough for TR PDFs up to several
  hundred pages; very large registers (1000+ pages) may need a paid tier or a
  self-hosted deployment (e.g. Render, Railway, or a college server) instead.
- No database is used — each session is stateless; the generated workbook only
  persists in that browser session (`st.session_state`) or once downloaded.

---

## How the PDF parser works (for maintainers)

The SGBAU TR PDF is a fixed positional template, not a real table, so text
extraction alone is unreliable. `tr_parser.py` instead:

1. Reads every word's `(x, y)` position on the page with `pdfplumber`.
2. Detects each student record by matching enrollment-number tokens
   (`\d{2}[A-Z]{2}\d{6}`, e.g. `25BO112804`).
3. Splits each record into a **left track** (roll no, name, mother's name,
   sex, medium — identified by fixed vertical offsets from the record start)
   and a **right track** (up to 12 subjects in a two-column layout, each with
   External / Internal / Grade Point marks).
4. Within each subject slot, marks tokens are collected while skipping
   re-attempt annotations (`@2`, `*1`) and exemption-status markers (`XM.I`,
   `XM.F`), and preserving absent/withheld placeholders (`AA`, `AB`) in the
   correct Ext/Int position.
5. The Subject Legend (full subject names) is harvested only from the
   footer paragraph of each page — never from body rows — to avoid
   mis-attributing garbled text as a subject name.

This approach is layout-based, not hardcoded to one college's subject list,
so it should generalize to other SGBAU TR PDFs using the same template
(different colleges, branches, or semesters). If a future TR uses a visibly
different layout, re-run the calibration in the "Row offset" section of
`parse_page()` against a sample page before trusting the output blindly —
**always spot-check a converted workbook against the source PDF** before
using it for official reporting.

## Extending the dashboard

`app.py` loads the workbook into a tidy `pandas` DataFrame
(`load_marks_dataframe`) with one row per student and `<code>__Ext`,
`<code>__Int`, `<code>__GP` columns per subject — a convenient shape for
adding new Plotly charts or filters on the **Interactive Charts** page.

## Customizing the Report Dashboard

`report.py`'s `build_report_html(df, subject_codes, legend, meta, title)`
returns a complete, self-contained HTML string (inline `<style>`, no external
requests) styled to match the reference template. It computes:

- KPIs (students, pass rate, failures, average marks/SGPA, highest SGPA)
- **Backlog analysis**: a backlog = a subject with recorded G.P. of 0;
  "applicable" subjects are those with any recorded G.P. for that student
- Result composition (pure-CSS conic-gradient donut), pass rate by gender
- Marks / SGPA / Medium distributions
- Subject-wise pass rate (G.P. > 0 = pass), color-coded weak/mid/good
- Top 10 by marks, highest backlog load table
- Auto-generated key insights and recommended interventions

Edit the CSS constant or the section-building logic in `report.py` to adjust
colors, thresholds (the weak/mid/good cutoffs are `<60% / 60–79% / ≥80%`), or
add new sections — the function is plain Python string templating, no
templating engine dependency required.
