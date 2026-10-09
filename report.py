"""
report.py — generates a single self-contained HTML analytics report that
visually matches the "First Year Result Analytics Dashboard" template
supplied by the user (preview_Updated_Sem_1_2025-26.html), but computed
dynamically from any converted TR workbook's DataFrame.

No JavaScript / chart libraries are used — everything is pure CSS (bar
fills, a conic-gradient donut, etc.) so the report renders identically
inside Streamlit (via st.components.v1.html) and as a standalone .html
file that can be opened, printed or emailed on its own.
"""

import html as _html
import pandas as pd

CSS = """
:root{--navy:#102a43;--blue:#1976d2;--cyan:#00a6c7;--green:#1b9e77;--red:#d64545;--amber:#e9a23b;--ink:#243b53;--muted:#627d98;--bg:#f3f6fa;--card:#fff;--border:#d9e2ec;--shadow:0 8px 24px rgba(16,42,67,.08)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--ink)}
.header{background:linear-gradient(135deg,#102a43,#1976d2);color:#fff;padding:26px 34px}.header h1{margin:0 0 6px;font-size:28px}.header p{margin:0;opacity:.9;font-size:14px}
.container{max-width:1500px;margin:auto;padding:22px}.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:18px}
.kpi,.card{background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow)}.kpi{padding:17px 18px}
.label{font-size:12px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.6px}.value{font-size:27px;font-weight:800;margin-top:6px;color:var(--navy)}.sub,.muted{font-size:11px;color:var(--muted)}
.card{padding:18px}.card h2{font-size:17px;margin:0 0 4px;color:var(--navy)}.desc{font-size:12px;color:var(--muted);margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}.grid3{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:18px;margin-bottom:18px}
.backlog-kpis{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}.bk{border:1px solid var(--border);border-radius:10px;padding:12px;background:#fbfdff;text-align:center}.bk .n{font-size:23px;font-weight:900;color:var(--red)}.bk .t{font-size:11px;color:var(--muted);font-weight:700;margin-top:3px}
.bars{display:grid;gap:10px}.bar-row{display:grid;grid-template-columns:90px 1fr 50px;gap:9px;align-items:center;font-size:12px}.bar-label{text-align:right;color:var(--muted);font-weight:700}.track{height:18px;background:#edf2f7;border-radius:5px;overflow:hidden}.fill{height:100%;border-radius:5px;background:linear-gradient(90deg,#1976d2,#00a6c7)}.bar-value{font-weight:800;text-align:right}
.callout{background:#fff8e8;border:1px solid #f1d28a;border-radius:10px;padding:12px;font-size:12px;line-height:1.5;margin-top:14px}
.donut-wrap{display:flex;align-items:center;justify-content:center;gap:28px;min-height:200px}.donut{width:170px;height:170px;border-radius:50%;position:relative}.donut:after{content:"";position:absolute;inset:34px;background:#fff;border-radius:50%}.donut-center{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;z-index:2;font-weight:900;font-size:27px;color:var(--navy)}.legend{display:grid;gap:12px}.legend-row{font-size:13px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px}.green-dot{background:var(--green)}.red-dot{background:var(--red)}
.subject-list{display:grid;gap:8px}.subject-row{display:grid;grid-template-columns:minmax(250px,2fr) 1fr 55px;gap:10px;align-items:center}.subject-name{font-size:12px;line-height:1.2}.subject-code{font-size:10px;color:var(--muted)}.subject-track{height:15px;background:#edf2f7;border-radius:5px;overflow:hidden}.subject-fill{height:100%;border-radius:5px}.good{background:#1b9e77}.mid{background:#e9a23b}.weak{background:#d64545}.subject-rate{font-weight:800;text-align:right;font-size:12px}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;background:#f5f8fb;color:var(--muted);padding:10px;border-bottom:1px solid var(--border)}td{padding:9px 10px;border-bottom:1px solid #edf2f7}tr:hover td{background:#f8fbff}.rank{font-weight:900;color:var(--blue)}.backlog-num{font-weight:900;color:var(--red);font-size:15px}
.insights{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.insight{padding:14px;border-radius:10px;background:#f7fafc;border-left:4px solid var(--blue);font-size:13px;line-height:1.45}.insight strong{color:var(--navy)}
.footer{font-size:11px;color:var(--muted);text-align:center;padding:20px 0 4px}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.backlog-kpis{grid-template-columns:repeat(4,1fr)}.grid3,.grid2{grid-template-columns:1fr}.insights{grid-template-columns:1fr}}
@media(max-width:650px){.kpis{grid-template-columns:repeat(2,1fr)}.backlog-kpis{grid-template-columns:repeat(2,1fr)}.container{padding:12px}.header{padding:20px}}
"""


def _esc(v) -> str:
    return _html.escape(str(v)) if v is not None else ""


def _bar_row(label, value_display, width_pct):
    width_pct = max(0.0, min(100.0, width_pct))
    return (
        f'<div class="bar-row"><div class="bar-label">{_esc(label)}</div>'
        f'<div class="track"><div class="fill" style="width:{width_pct:.1f}%"></div></div>'
        f'<div class="bar-value">{_esc(value_display)}</div></div>'
    )


def _compute_backlogs(df: pd.DataFrame, subject_codes: list[str]) -> pd.DataFrame:
    """Returns a copy of df with 'Applicable', 'Backlogs' columns added.
    A backlog = a subject with a recorded G.P. of 0 for that student.
    'Applicable' = number of subjects with any recorded G.P. for that student."""
    gp_cols = [f"{c}__GP" for c in subject_codes if f"{c}__GP" in df.columns]
    gp_numeric = df[gp_cols].apply(pd.to_numeric, errors="coerce")
    applicable = gp_numeric.notna().sum(axis=1)
    backlogs = (gp_numeric == 0).sum(axis=1)
    out = df.copy()
    out["Applicable"] = applicable
    out["Backlogs"] = backlogs
    return out


def build_report_html(df: pd.DataFrame, subject_codes: list[str], legend: dict,
                       meta: dict | None = None, title: str | None = None) -> str:
    meta = meta or {}
    df = _compute_backlogs(df, subject_codes)
    total = len(df)
    passed = int((df["Result"] == "PASS").sum())
    failed = total - passed
    pass_rate = 100 * passed / total if total else 0
    avg_marks = df["Marks Obtained"].mean()
    avg_pct = df["Percentage"].mean()
    avg_sgpa = df["SGPA"].mean()
    max_sgpa = df["SGPA"].max()

    # ---------------- Backlog analysis ----------------
    bl = df["Backlogs"].clip(upper=6)  # bucket 6+ together
    bucket_counts = {i: int((bl == i).sum()) for i in range(6)}
    six_plus = int((df["Backlogs"] >= 6).sum())
    all_applicable_backlogs = int(((df["Backlogs"] == df["Applicable"]) & (df["Applicable"] > 0)).sum())
    bucket_max = max(list(bucket_counts.values()) + [six_plus] + [1])

    backlog_kpi_html = "".join(
        f'<div class="bk"><div class="n">{bucket_counts[i]}</div><div class="t">{lbl}</div></div>'
        for i, lbl in [(0, "No Backlog"), (1, "1 Backlog"), (2, "2 Backlogs"),
                       (3, "3 Backlogs"), (4, "4 Backlogs"), (5, "5 Backlogs")]
    ) + f'<div class="bk"><div class="n">{all_applicable_backlogs}</div><div class="t">All Applicable Backlogs</div></div>'

    backlog_bars_html = "".join([
        _bar_row("No Backlog", bucket_counts[0], 100 * bucket_counts[0] / bucket_max),
        _bar_row("1 Backlog", bucket_counts[1], 100 * bucket_counts[1] / bucket_max),
        _bar_row("2 Backlogs", bucket_counts[2], 100 * bucket_counts[2] / bucket_max),
        _bar_row("3 Backlogs", bucket_counts[3], 100 * bucket_counts[3] / bucket_max),
        _bar_row("4 Backlogs", bucket_counts[4], 100 * bucket_counts[4] / bucket_max),
        _bar_row("5 Backlogs", bucket_counts[5], 100 * bucket_counts[5] / bucket_max),
        _bar_row("6+ Backlogs", six_plus, 100 * six_plus / bucket_max),
    ])

    two_three = bucket_counts[2] + bucket_counts[3]
    four_plus = six_plus + sum(bucket_counts[i] for i in (4, 5))

    # ---------------- Result composition donut ----------------
    donut_style = (
        f"background:conic-gradient(var(--green) 0 {pass_rate}%,"
        f"var(--red) {pass_rate}% 100%)"
    )

    # ---------------- Pass rate by gender ----------------
    gender_rows = ""
    if "Sex" in df.columns and df["Sex"].notna().any():
        for sex, grp in df.groupby("Sex"):
            if not sex or str(sex).strip() == "" or str(sex).lower() == "nan":
                continue
            rate = 100 * (grp["Result"] == "PASS").sum() / len(grp) if len(grp) else 0
            label = {"F": "Female", "M": "Male"}.get(str(sex).upper(), str(sex))
            gender_rows += _bar_row(label, f"{rate:.1f}%", rate)

    # ---------------- Marks distribution ----------------
    marks_bins = [(-0.01, 50, "<50%"), (50, 60, "50–59%"), (60, 70, "60–69%"),
                  (70, 80, "70–79%"), (80, 90, "80–89%"), (90, 100.01, "90–100%")]
    marks_counts = []
    for lo, hi, lbl in marks_bins:
        c = int(((df["Percentage"] >= lo) & (df["Percentage"] < hi)).sum())
        marks_counts.append((lbl, c))
    mmax = max([c for _, c in marks_counts] + [1])
    marks_html = "".join(_bar_row(lbl, c, 100 * c / mmax) for lbl, c in marks_counts)

    # ---------------- SGPA distribution ----------------
    sgpa_bins = [(-0.01, 6, "<6"), (6, 7, "6–6.99"), (7, 8, "7–7.99"),
                 (8, 9, "8–8.99"), (9, 10.01, "9–10")]
    sgpa_valid = df["SGPA"].dropna()
    sgpa_counts = []
    for lo, hi, lbl in sgpa_bins:
        c = int(((sgpa_valid >= lo) & (sgpa_valid < hi)).sum())
        sgpa_counts.append((lbl, c))
    smax = max([c for _, c in sgpa_counts] + [1])
    sgpa_html = "".join(_bar_row(lbl, c, 100 * c / smax) for lbl, c in sgpa_counts)

    # ---------------- Medium composition ----------------
    med_html = ""
    if "Medium" in df.columns and df["Medium"].notna().any():
        med_counts = df["Medium"].dropna().value_counts()
        med_max = max(list(med_counts.values) + [1])
        for med, c in med_counts.items():
            med_html += _bar_row(med, int(c), 100 * c / med_max)

    # ---------------- Subject-wise pass rate ----------------
    subj_rows = []
    for code in subject_codes:
        gp_col = f"{code}__GP"
        if gp_col not in df.columns:
            continue
        gp = pd.to_numeric(df[gp_col], errors="coerce")
        n = int(gp.notna().sum())
        if n == 0:
            continue
        passed_n = int((gp > 0).sum())
        rate = 100 * passed_n / n
        subj_rows.append((legend.get(code, code), code, n, rate))
    subj_rows.sort(key=lambda r: r[3])
    weakest = subj_rows[0] if subj_rows else None

    subject_list_html = ""
    for name, code, n, rate in subj_rows:
        cls = "weak" if rate < 60 else ("mid" if rate < 80 else "good")
        subject_list_html += (
            f'<div class="subject-row"><div class="subject-name"><b>{_esc(name)}</b>'
            f'<div class="subject-code">{_esc(code)} • n={n}</div></div>'
            f'<div class="subject-track"><div class="subject-fill {cls}" style="width:{rate:.1f}%"></div></div>'
            f'<div class="subject-rate">{rate:.1f}%</div></div>'
        )

    # ---------------- Top 10 by marks ----------------
    top10 = df.sort_values(["Marks Obtained", "SGPA"], ascending=False).head(10)
    top_rows = ""
    for i, (_, r) in enumerate(top10.iterrows(), start=1):
        pct = r.get("Percentage")
        sgpa = r.get("SGPA")
        marks = r.get("Marks Obtained")
        outof = r.get("Out Of")
        marks_disp = f'{int(marks)}' if pd.notna(marks) else "—"
        outof_disp = f'{int(outof)}' if pd.notna(outof) else "—"
        pct_disp = f'{pct:.1f}%' if pd.notna(pct) else "—"
        sgpa_disp = f'{sgpa}' if pd.notna(sgpa) else "—"
        top_rows += (
            f'<tr><td class="rank">#{i}</td>'
            f'<td><b>{_esc(r["Name of Candidate"])}</b><br><span class="muted">{_esc(r["Enrollment No"])}</span></td>'
            f'<td>{marks_disp}/{outof_disp}</td>'
            f'<td>{pct_disp}</td>'
            f'<td>{sgpa_disp}</td>'
            f'<td>{int(r["Backlogs"])}</td>'
            f'<td>{_esc(r["Result"])}</td></tr>'
        )

    # ---------------- Highest backlog load ----------------
    worst = df.sort_values(["Backlogs", "Marks Obtained"], ascending=[False, True]).head(10)
    worst_rows = ""
    for _, r in worst.iterrows():
        if r["Backlogs"] <= 0:
            continue
        marks = r.get("Marks Obtained")
        outof = r.get("Out Of")
        marks_disp = f'{int(marks)}' if pd.notna(marks) else "—"
        outof_disp = f'{int(outof)}' if pd.notna(outof) else "—"
        worst_rows += (
            f'<tr><td><b>{_esc(r["Name of Candidate"])}</b><br><span class="muted">{_esc(r["Enrollment No"])}</span></td>'
            f'<td class="backlog-num">{int(r["Backlogs"])}</td>'
            f'<td>{marks_disp}/{outof_disp}</td>'
            f'<td>{_esc(r["Result"])}</td></tr>'
        )

    # ---------------- Key insights ----------------
    marks_ge60 = int((df["Percentage"] >= 60).sum())
    sgpa_total = int(df["SGPA"].notna().sum())
    sgpa_ge8 = int((df["SGPA"] >= 8).sum())

    insights = [
        f'<strong>Overall:</strong> {passed} passed and {failed} failed; overall pass rate is <b>{pass_rate:.1f}%</b>.',
        f'<strong>One backlog:</strong> <b>{bucket_counts[1]}</b> students have exactly one failed subject.',
        f'<strong>Two backlogs:</strong> <b>{bucket_counts[2]}</b> students have exactly two failed subjects.',
        f'<strong>Three backlogs:</strong> <b>{bucket_counts[3]}</b> students have exactly three failed subjects.',
        f'<strong>4+ backlogs:</strong> <b>{four_plus}</b> students have four or more failed subjects.',
        f'<strong>All applicable backlogs:</strong> <b>{all_applicable_backlogs}</b> students failed every applicable subject recorded for them.',
        f'<strong>Marks:</strong> {marks_ge60} students ({100*marks_ge60/total:.1f}%) scored at least 60%.' if total else '',
        (f'<strong>SGPA:</strong> {sgpa_ge8} of {sgpa_total} students with SGPA '
         f'({100*sgpa_ge8/sgpa_total:.1f}%) are at 8.00 or above.') if sgpa_total else '',
    ]
    if weakest:
        insights.append(
            f'<strong>Weakest subject:</strong> {_esc(weakest[0])} ({_esc(weakest[1])}) '
            f'has a {weakest[3]:.1f}% pass rate.'
        )
    insights_html = "".join(f'<div class="insight">{ins}</div>' for ins in insights if ins)

    college = meta.get("college", "")
    exam_title = meta.get("exam_title", "")
    report_title = title or "Result Analytics Dashboard"
    subtitle_bits = [b for b in [college, exam_title] if b]
    subtitle = " — ".join(subtitle_bits) if subtitle_bits else "Tabulation Register analysis"

    n_subjects = len(subj_rows)

    html_out = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_esc(report_title)}</title>
<style>{CSS}</style></head><body>
<div class="header"><h1>{_esc(report_title)}</h1>
<p>{_esc(subtitle)} • {total} students • {n_subjects} grade-point subjects identified</p></div>
<div class="container">

<div class="kpis">
<div class="kpi"><div class="label">Total Students</div><div class="value">{total}</div><div class="sub">Records analysed</div></div>
<div class="kpi"><div class="label">Pass Rate</div><div class="value">{pass_rate:.1f}%</div><div class="sub">{passed} passed</div></div>
<div class="kpi"><div class="label">Failures</div><div class="value">{failed}</div><div class="sub">Result marked FAIL</div></div>
<div class="kpi"><div class="label">Average Marks</div><div class="value">{avg_marks:.1f}</div><div class="sub">out of {int(df["Out Of"].mode()[0]) if not df["Out Of"].mode().empty else 750} • {avg_pct:.1f}%</div></div>
<div class="kpi"><div class="label">Average SGPA</div><div class="value">{avg_sgpa:.2f}</div><div class="sub">recorded SGPA</div></div>
<div class="kpi"><div class="label">Highest SGPA</div><div class="value">{max_sgpa:.2f}</div><div class="sub">recorded maximum</div></div>
</div>

<div class="card" style="margin-bottom:18px">
<h2>Backlog Analysis — Subject-wise Failure Load</h2>
<div class="desc">A backlog is counted when a student's recorded G.P. is 0. Blank G.P. cells are treated as not applicable. "All Backlogs" means the student failed every applicable subject recorded for them.</div>
<div class="backlog-kpis">{backlog_kpi_html}</div>
<div class="grid2" style="margin-top:16px;margin-bottom:0">
<div><div class="bars">{backlog_bars_html}</div>
<div class="callout"><b>6+ backlogs:</b> {six_plus} students. <b>All applicable subjects failed:</b> {all_applicable_backlogs} students.</div></div>
<div class="card" style="box-shadow:none;background:#f8fbff"><h2 style="font-size:15px">Backlog Intervention Cohorts</h2>
<p style="font-size:13px;line-height:1.55"><b>{bucket_counts[1]}</b> students have exactly one backlog; these are the most focused remediation candidates.</p>
<p style="font-size:13px;line-height:1.55"><b>{bucket_counts[2]}</b> have two backlogs and <b>{bucket_counts[3]}</b> have three backlogs.</p>
<p style="font-size:13px;line-height:1.55"><b>{four_plus}</b> students have four or more backlogs and should receive higher-intensity academic support.</p>
</div></div>
</div>

<div class="grid2">
<div class="card"><h2>Overall Result Composition</h2><div class="desc">Pass vs fail across the complete cohort.</div>
<div class="donut-wrap"><div class="donut" style="{donut_style}"><div class="donut-center">{pass_rate:.1f}%</div></div><div class="legend">
<div class="legend-row"><span class="dot green-dot"></span><b>PASS</b> — {passed} ({pass_rate:.1f}%)</div>
<div class="legend-row"><span class="dot red-dot"></span><b>FAIL</b> — {failed} ({100-pass_rate:.1f}%)</div></div></div></div>
<div class="card"><h2>Pass Rate by Gender</h2><div class="desc">Comparison of cohort outcome performance.</div><div class="bars">{gender_rows}</div></div>
</div>

<div class="grid3">
<div class="card"><h2>Marks Distribution</h2><div class="desc">Percentage bands based on Marks Obtained / Out Of.</div><div class="bars">{marks_html}</div></div>
<div class="card"><h2>SGPA Distribution</h2><div class="desc">Students with recorded SGPA.</div><div class="bars">{sgpa_html}</div></div>
<div class="card"><h2>Medium Composition</h2><div class="desc">Medium recorded in the result sheet.</div><div class="bars">{med_html}</div></div>
</div>

<div class="card" style="margin-bottom:18px"><h2>Subject-wise Pass Rate</h2><div class="desc">G.P. &gt; 0 is treated as a subject pass. Cohort size is shown because some subjects are branch-specific.</div><div class="subject-list">{subject_list_html}</div></div>

<div class="grid2">
<div class="card"><h2>Top 10 Students by Total Marks</h2><div class="desc">Ranked by total marks; SGPA is secondary.</div>
<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Student</th><th>Marks</th><th>%</th><th>SGPA</th><th>Backlogs</th><th>Result</th></tr></thead><tbody>{top_rows}</tbody></table></div></div>
<div class="card"><h2>Highest Backlog Load</h2><div class="desc">Students with the greatest number of failed subjects.</div>
<div class="table-wrap"><table><thead><tr><th>Student</th><th>Backlogs</th><th>Marks</th><th>Result</th></tr></thead><tbody>{worst_rows}</tbody></table></div></div>
</div>

<div class="card" style="margin-bottom:18px"><h2>Key Academic Insights</h2><div class="desc">Automatically derived from the supplied result sheet.</div>
<div class="insights">{insights_html}</div></div>

<div class="card"><h2>Recommended Academic Intervention</h2><div class="desc">Suggested actions based on the backlog pattern.</div>
<ol style="margin:8px 0 0 20px;line-height:1.7;font-size:13px">
<li>Create a dedicated remediation list for the <b>{bucket_counts[1]}</b> one-backlog students.</li>
<li>Run focused support for the <b>{bucket_counts[2]}</b> two-backlog and <b>{bucket_counts[3]}</b> three-backlog cohorts.</li>
<li>Escalate the <b>{four_plus}</b> students with 4+ backlogs for individualized academic counselling.</li>
<li>Use the subject-wise pass-rate section to prioritize tutorial/remedial sessions in weak subjects.</li>
</ol></div>
<div class="footer">Generated by the SGBAU TR → Excel & Dashboard app • All dashboard sections and charts are visible on one page.</div>
</div></body></html>"""
    return html_out
