"""
SGBAU Tabulation Register -> Excel converter + Interactive Results Dashboard
=============================================================================
A single Streamlit app with two tools:
  1) Convert TR (PDF) -> a clean, analysis-ready Excel workbook
  2) Explore that Excel through an interactive results dashboard

Run locally:
    streamlit run app.py

Deploy for free on Streamlit Community Cloud:
    see README.md
"""

import io
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from tr_parser import parse_pdf, records_to_rows, build_workbook
from report import build_report_html

st.set_page_config(
    page_title="SGBAU TR → Excel & Dashboard",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_marks_dataframe(file_bytes: bytes) -> tuple[pd.DataFrame, list[str], dict]:
    """Read the 'Marks Data' + 'Subject Legend' sheets of a generated workbook
    into a tidy pandas DataFrame plus the ordered list of subject codes."""
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    raw = pd.read_excel(xls, sheet_name="Marks Data", header=[0, 1, 2])
    legend_df = pd.read_excel(xls, sheet_name="Subject Legend")
    # Subject codes may be purely numeric (e.g. "17504") and get read back from
    # Excel as int64 - cast to str so they match the string keys used everywhere
    # else (subject_codes list, column names), regardless of the TR's coding scheme.
    # A subject with no legend entry was written as a blank cell, which pandas
    # reads back as NaN - fall back to the code itself in that case.
    legend_df["Subject Code"] = legend_df["Subject Code"].astype(str)
    legend_df["Subject Name"] = legend_df["Subject Name"].where(
        legend_df["Subject Name"].notna() & (legend_df["Subject Name"].astype(str).str.strip() != ""),
        legend_df["Subject Code"],
    )
    legend = dict(zip(legend_df["Subject Code"], legend_df["Subject Name"]))

    fixed_names = ["S.No", "Enrollment No", "Name of Candidate", "Mother's Name",
                   "Sex", "Medium", "Marks Obtained", "Out Of", "Result", "SGPA",
                   "Total Credit Earned"]
    n_fixed = len(fixed_names)

    df = pd.DataFrame()
    for i, name in enumerate(fixed_names):
        df[name] = raw.iloc[:, i]

    subject_codes = []
    cols = raw.columns
    i = n_fixed
    while i < len(cols):
        code = str(cols[i][1]).strip()
        if code.lower().startswith("unnamed") or code == "nan":
            i += 1
            continue
        subject_codes.append(code)
        df[f"{code}__Ext"] = raw.iloc[:, i]
        df[f"{code}__Int"] = raw.iloc[:, i + 1]
        df[f"{code}__GP"] = raw.iloc[:, i + 2]
        i += 3

    df["SGPA"] = pd.to_numeric(df["SGPA"], errors="coerce")
    df["Marks Obtained"] = pd.to_numeric(df["Marks Obtained"], errors="coerce")
    df["Out Of"] = pd.to_numeric(df["Out Of"], errors="coerce")
    df["Percentage"] = (df["Marks Obtained"] / df["Out Of"] * 100).round(2)
    df["Result"] = df["Result"].astype(str).str.strip()

    return df, subject_codes, legend


def subject_stats(df: pd.DataFrame, subject_codes: list[str], legend: dict) -> pd.DataFrame:
    cols = ["Code", "Subject", "Appeared", "Avg Ext Marks", "Avg Grade Point",
            "Fail Count", "Fail %"]
    rows = []
    for code in subject_codes:
        gp_col = f"{code}__GP"
        if gp_col not in df.columns:
            continue
        gp = pd.to_numeric(df[gp_col], errors="coerce")
        ext = pd.to_numeric(df[f"{code}__Ext"], errors="coerce")
        appeared = gp.notna().sum()
        fail_mask = gp == 0
        rows.append({
            "Code": code,
            "Subject": legend.get(code, code),
            "Appeared": int(appeared),
            "Avg Ext Marks": round(ext.mean(), 1) if ext.notna().any() else None,
            "Avg Grade Point": round(gp.mean(), 2) if gp.notna().any() else None,
            "Fail Count": int(fail_mask.sum()),
            "Fail %": round(100 * fail_mask.sum() / appeared, 1) if appeared else 0,
        })
    if not rows:
        # No subject columns matched (e.g. an unexpected TR layout) - return an
        # empty-but-well-formed frame instead of crashing sort_values downstream.
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values("Fail %", ascending=False)


def arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Make a DataFrame safe to pass to st.dataframe().

    Streamlit renders tables via PyArrow, which refuses to infer a single
    type for an "object" column that mixes numbers with strings - which is
    exactly what raw Ext/Int/G.P. mark columns can contain (a normal numeric
    mark alongside an absent/withheld placeholder like 'AA' or 'AB' for
    another student). That mix crashes the whole page with an ArrowInvalid
    error instead of just that one column. Any object-dtype column here is
    cast to a clean string column (blanks for missing values) so every
    column has one uniform, Arrow-friendly type; numeric/bool/datetime
    columns are left untouched so they still sort and format as numbers.
    """
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == object:
            safe[col] = safe[col].apply(lambda v: "" if pd.isna(v) else str(v))
    return safe


def kpi(label, value, help_text=None):
    st.metric(label, value, help=help_text)


# ----------------------------------------------------------------------------
# Sidebar navigation
# ----------------------------------------------------------------------------

st.sidebar.title("🎓 TR Toolkit")
page = st.sidebar.radio(
    "Choose a tool",
    ["📄 Convert TR → Excel", "📋 Report Dashboard", "📊 Interactive Charts"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.caption(
    "Built for Sant Gadge Baba Amravati University (SGBAU) Tabulation Registers. "
    "Works with the standard multi-column TR PDF layout used across colleges/branches."
)

if "workbook_bytes" not in st.session_state:
    st.session_state.workbook_bytes = None
if "workbook_name" not in st.session_state:
    st.session_state.workbook_name = None
if "last_meta" not in st.session_state:
    st.session_state.last_meta = {}

# ----------------------------------------------------------------------------
# PAGE 1: Convert TR PDF -> Excel
# ----------------------------------------------------------------------------

if page == "📄 Convert TR → Excel":
    st.title("📄 Convert Tabulation Register (PDF) → Excel")
    st.write(
        "Upload the official SGBAU Tabulation Register PDF. The app extracts every "
        "student's roll number, name, mother's name, sex, medium, subject-wise "
        "External / Internal / Grade Point marks, SGPA, result and credits into a "
        "clean, structured Excel workbook — ready for the dashboard or your own analysis."
    )

    uploaded_pdf = st.file_uploader("Upload TR PDF", type=["pdf"])

    if uploaded_pdf is not None:
        st.info(f"**{uploaded_pdf.name}** — {uploaded_pdf.size / 1024:.0f} KB")
        if st.button("🚀 Convert to Excel", type="primary"):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_pdf.getvalue())
                tmp_path = tmp.name

            progress_bar = st.progress(0.0, text="Starting…")

            def _cb(done, total):
                progress_bar.progress(done / total, text=f"Reading page {done} of {total}…")

            try:
                records, legend, meta = parse_pdf(tmp_path, progress_cb=_cb)
                progress_bar.progress(1.0, text="Building Excel workbook…")
                rows, subject_order = records_to_rows(records, legend, out_of=meta.get("out_of", 750))

                out_path = Path(tempfile.gettempdir()) / f"{Path(uploaded_pdf.name).stem}_converted.xlsx"
                build_workbook(rows, subject_order, legend, str(out_path), meta=meta)

                st.session_state.workbook_bytes = out_path.read_bytes()
                st.session_state.workbook_name = out_path.name
                st.session_state.last_meta = meta

                progress_bar.progress(1.0, text="Done!")
                st.success(
                    f"✅ Converted **{len(rows)} students** across **{len(subject_order)} subjects** "
                    f"from **{len(records) and meta.get('college', 'the uploaded TR')}**."
                )

                c1, c2, c3 = st.columns(3)
                passed = sum(1 for r in rows if r.get("Result") == "PASS")
                c1.metric("Students", len(rows))
                c2.metric("Pass %", f"{100*passed/len(rows):.1f}%" if rows else "—")
                c3.metric("Subjects detected", len(subject_order))

                st.download_button(
                    "⬇️ Download Excel workbook",
                    data=st.session_state.workbook_bytes,
                    file_name=st.session_state.workbook_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )

                with st.expander("Preview first 15 rows"):
                    preview_df = pd.DataFrame(rows).head(15)
                    st.dataframe(arrow_safe(preview_df), width='stretch')

                st.info(
                    "👉 Head to **📋 Report Dashboard** in the sidebar for the full analytics "
                    "report — it will automatically use the file you just generated, or you "
                    "can upload any previously converted workbook there."
                )
            except Exception as e:
                st.error(f"Something went wrong while parsing this PDF: {e}")
                st.exception(e)
    else:
        st.markdown(
            "*No file uploaded yet — drop a TR PDF above to begin. "
            "Typical file: `<College>_TR_<Year>.pdf` exported from the SGBAU results portal.*"
        )

# ----------------------------------------------------------------------------
# Shared: load the workbook (from session state or a fresh upload)
# ----------------------------------------------------------------------------

def get_workbook_source(key_suffix: str):
    source = None
    if st.session_state.workbook_bytes is not None:
        use_last = st.checkbox(
            f"Use the workbook just generated ({st.session_state.workbook_name})",
            value=True,
            key=f"use_last_{key_suffix}",
        )
        if use_last:
            source = st.session_state.workbook_bytes

    if source is None:
        uploaded_xlsx = st.file_uploader(
            "Upload a converted Marks Data Excel workbook", type=["xlsx"],
            key=f"upload_{key_suffix}",
        )
        if uploaded_xlsx is not None:
            source = uploaded_xlsx.getvalue()
    return source


# ----------------------------------------------------------------------------
# PAGE 2: Report Dashboard (matches the supplied HTML template design)
# ----------------------------------------------------------------------------

if page == "📋 Report Dashboard":
    st.title("📋 Report Dashboard")
    st.caption(
        "A single-page, printable analytics report — same layout as your reference "
        "template — generated live from the converted workbook below."
    )

    source = get_workbook_source("report")
    if source is None:
        st.info("Convert a TR PDF first, or upload a previously converted Excel workbook.")
        st.stop()

    with st.spinner("Loading data…"):
        df, subject_codes, legend = load_marks_dataframe(source)

    # ---------------- Filters ----------------
    with st.sidebar:
        st.markdown("### 🔎 Filters")
        result_opts = sorted(df["Result"].dropna().unique().tolist())
        sel_result = st.multiselect("Result", result_opts, default=result_opts, key="rd_result")
        sex_opts = sorted(df["Sex"].dropna().unique().tolist())
        sel_sex = st.multiselect("Sex", sex_opts, default=sex_opts, key="rd_sex")
        med_opts = sorted(df["Medium"].dropna().unique().tolist())
        sel_med = st.multiselect("Medium", med_opts, default=med_opts, key="rd_med")
        report_title = st.text_input(
            "Report title", value="First Year Students — Result Analytics Dashboard",
            key="rd_title",
        )

    fdf = df[
        df["Result"].isin(sel_result)
        & df["Sex"].isin(sel_sex)
        & df["Medium"].isin(sel_med)
    ]

    if fdf.empty:
        st.warning("No students match the selected filters.")
        st.stop()

    meta = {}
    if st.session_state.get("last_meta"):
        meta = st.session_state.last_meta

    report_html = build_report_html(fdf, subject_codes, legend, meta=meta, title=report_title)

    st.download_button(
        "⬇️ Download standalone HTML report",
        data=report_html.encode("utf-8"),
        file_name="result_analytics_dashboard.html",
        mime="text/html",
        type="primary",
    )

    st.iframe(src=report_html, height=7200)

# ----------------------------------------------------------------------------
# PAGE 3: Interactive Charts (Plotly — bonus deep-dive view)
# ----------------------------------------------------------------------------

else:
    st.title("📊 Interactive Charts")
    st.caption("A supplementary, filterable Plotly view for deeper exploration.")

    source = get_workbook_source("charts")
    if source is None:
        st.info("Convert a TR PDF first, or upload a previously converted Excel workbook.")
        st.stop()

    with st.spinner("Loading data…"):
        df, subject_codes, legend = load_marks_dataframe(source)

    # ---------------- Filters ----------------
    with st.sidebar:
        st.markdown("### 🔎 Filters")
        result_opts = sorted(df["Result"].dropna().unique().tolist())
        sel_result = st.multiselect("Result", result_opts, default=result_opts, key="ic_result")
        sex_opts = sorted(df["Sex"].dropna().unique().tolist())
        sel_sex = st.multiselect("Sex", sex_opts, default=sex_opts, key="ic_sex")
        med_opts = sorted(df["Medium"].dropna().unique().tolist())
        sel_med = st.multiselect("Medium", med_opts, default=med_opts, key="ic_med")

    fdf = df[
        df["Result"].isin(sel_result)
        & df["Sex"].isin(sel_sex)
        & df["Medium"].isin(sel_med)
    ]

    if fdf.empty:
        st.warning("No students match the selected filters.")
        st.stop()

    # ---------------- KPI row ----------------
    total = len(fdf)
    passed = (fdf["Result"] == "PASS").sum()
    failed = total - passed
    avg_sgpa = fdf.loc[fdf["Result"] == "PASS", "SGPA"].mean()
    avg_pct = fdf["Percentage"].mean()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Students", f"{total}")
    c2.metric("Passed", f"{passed}", f"{100*passed/total:.1f}%")
    c3.metric("Failed", f"{failed}", f"-{100*failed/total:.1f}%", delta_color="inverse")
    c4.metric("Avg SGPA (passed)", f"{avg_sgpa:.2f}" if pd.notna(avg_sgpa) else "—")
    c5.metric("Avg Aggregate %", f"{avg_pct:.1f}%" if pd.notna(avg_pct) else "—")

    st.markdown("---")

    tabs = st.tabs([
        "🏁 Overview", "📚 Subject Analysis", "🏆 Toppers & Distribution",
        "👥 Demographics", "🗂️ Raw Data",
    ])

    # ---- Overview ----
    with tabs[0]:
        col1, col2 = st.columns(2)
        with col1:
            res_counts = fdf["Result"].value_counts().reset_index()
            res_counts.columns = ["Result", "Count"]
            fig = px.pie(
                res_counts, names="Result", values="Count", hole=0.45,
                title="Result Distribution",
                color="Result",
                color_discrete_map={"PASS": "#2E7D32", "FAIL": "#C62828"},
            )
            fig.update_traces(textinfo="percent+label")
            st.plotly_chart(fig, width='stretch')
        with col2:
            sgpa_df = fdf[fdf["Result"] == "PASS"].dropna(subset=["SGPA"])
            if not sgpa_df.empty:
                fig2 = px.histogram(
                    sgpa_df, x="SGPA", nbins=20, title="SGPA Distribution (Passed Students)",
                    color_discrete_sequence=["#1565C0"],
                )
                fig2.update_layout(bargap=0.05)
                st.plotly_chart(fig2, width='stretch')
            else:
                st.info("No SGPA data available for passed students in this filter.")

        col3, col4 = st.columns(2)
        with col3:
            fig3 = px.histogram(
                fdf.dropna(subset=["Percentage"]), x="Percentage", nbins=25,
                title="Aggregate % Distribution", color_discrete_sequence=["#6A1B9A"],
            )
            fig3.update_layout(bargap=0.05)
            st.plotly_chart(fig3, width='stretch')
        with col4:
            credit_df = fdf.dropna(subset=["Total Credit Earned"])
            fig4 = px.histogram(
                credit_df, x="Total Credit Earned", title="Credits Earned Distribution",
                color_discrete_sequence=["#EF6C00"],
            )
            st.plotly_chart(fig4, width='stretch')

    # ---- Subject Analysis ----
    with tabs[1]:
        st.subheader("Subject-wise Performance")
        sdf = subject_stats(fdf, subject_codes, legend)
        if sdf.empty:
            st.info("No subject columns detected.")
        else:
            metric = st.radio(
                "Rank subjects by", ["Fail %", "Avg Grade Point", "Avg Ext Marks"],
                horizontal=True,
            )
            top_n = st.slider("Show top N subjects", 5, min(30, len(sdf)), min(15, len(sdf)))
            plot_df = sdf.sort_values(metric, ascending=(metric != "Fail %")).head(top_n) \
                if metric != "Fail %" else sdf.head(top_n)
            fig = px.bar(
                plot_df.sort_values(metric), x=metric, y="Subject", orientation="h",
                title=f"Subjects ranked by {metric}", color=metric,
                color_continuous_scale="Reds" if metric == "Fail %" else "Blues",
                hover_data=["Code", "Appeared"],
            )
            fig.update_layout(yaxis_title="", height=max(400, 28 * top_n))
            st.plotly_chart(fig, width='stretch')

            st.dataframe(arrow_safe(sdf.reset_index(drop=True)), width='stretch')

    # ---- Toppers & Distribution ----
    with tabs[2]:
        st.subheader("Top Performers")
        n = st.slider("Number of toppers to show", 5, 30, 10)
        topper_df = (
            fdf[fdf["Result"] == "PASS"]
            .dropna(subset=["SGPA"])
            .sort_values(["SGPA", "Marks Obtained"], ascending=False)
            .head(n)[["Enrollment No", "Name of Candidate", "SGPA", "Marks Obtained",
                      "Percentage", "Total Credit Earned"]]
            .reset_index(drop=True)
        )
        topper_df.index += 1
        st.dataframe(arrow_safe(topper_df), width='stretch')

        st.subheader("Grade-Point Heatmap (sampled subjects × students)")
        gp_cols = [f"{c}__GP" for c in subject_codes if f"{c}__GP" in fdf.columns]
        if gp_cols:
            sample = fdf.sample(min(40, len(fdf)), random_state=1).sort_values("SGPA", ascending=False)
            heat = sample[gp_cols].apply(pd.to_numeric, errors="coerce")
            heat.columns = [legend.get(c.replace("__GP", ""), c) for c in gp_cols]
            heat.index = sample["Name of Candidate"].str.slice(0, 22)
            fig = go.Figure(data=go.Heatmap(
                z=heat.values, x=heat.columns, y=heat.index,
                colorscale="RdYlGn", zmin=0, zmax=10,
            ))
            fig.update_layout(height=700, xaxis_tickangle=-45)
            st.plotly_chart(fig, width='stretch')

    # ---- Demographics ----
    with tabs[3]:
        col1, col2 = st.columns(2)
        with col1:
            gsex = fdf.groupby(["Sex", "Result"]).size().reset_index(name="Count")
            fig = px.bar(
                gsex, x="Sex", y="Count", color="Result", barmode="group",
                title="Result by Sex",
                color_discrete_map={"PASS": "#2E7D32", "FAIL": "#C62828"},
            )
            st.plotly_chart(fig, width='stretch')
        with col2:
            gmed = fdf.groupby(["Medium", "Result"]).size().reset_index(name="Count")
            fig2 = px.bar(
                gmed, x="Medium", y="Count", color="Result", barmode="group",
                title="Result by Medium of Instruction",
                color_discrete_map={"PASS": "#2E7D32", "FAIL": "#C62828"},
            )
            st.plotly_chart(fig2, width='stretch')

        col3, col4 = st.columns(2)
        with col3:
            sgpa_sex = fdf[fdf["Result"] == "PASS"].dropna(subset=["SGPA"])
            if not sgpa_sex.empty:
                fig3 = px.box(sgpa_sex, x="Sex", y="SGPA", color="Sex", title="SGPA Spread by Sex")
                st.plotly_chart(fig3, width='stretch')
        with col4:
            pass_rate = fdf.groupby("Sex")["Result"].apply(
                lambda s: 100 * (s == "PASS").sum() / len(s)
            ).reset_index(name="Pass %")
            fig4 = px.bar(pass_rate, x="Sex", y="Pass %", title="Pass % by Sex", text_auto=".1f")
            st.plotly_chart(fig4, width='stretch')

    # ---- Raw data ----
    with tabs[4]:
        st.subheader("Filtered Student Records")
        show_cols = ["S.No", "Enrollment No", "Name of Candidate", "Mother's Name",
                     "Sex", "Medium", "Marks Obtained", "Out Of", "Percentage",
                     "Result", "SGPA", "Total Credit Earned"]
        st.dataframe(arrow_safe(fdf[show_cols].reset_index(drop=True)), width='stretch', height=500)
        csv = fdf[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download filtered data as CSV", csv, "filtered_results.csv", "text/csv")
