import re
import pdfplumber
from collections import defaultdict, Counter

ENROLL_RE = re.compile(r'^\d{2}[A-Z]{2}\d{6}$')
# Subject codes appear in two schemes across SGBAU TR templates:
#   - alphanumeric, e.g. "1AL100BS", "2AL118VS3"  (NEP first-year pattern)
#   - plain 5-digit numeric, e.g. "17504", "16470" (CBCS higher-semester pattern)
SUBJECT_RE = re.compile(r'^(?:\d[A-Z]{2}\d{2,3}[A-Z0-9]{0,6}|\d{5})$')
STATUS_RE = re.compile(r'^[A-Z]{2}\.[A-Z]$')  # XM.I, XM.F etc
NUM_RE = re.compile(r'^\d+(\.\d+)?$')
PLACEHOLDER_RE = re.compile(r'^(AA|AB|RR|RPV|--)$')  # Absent / withheld style markers that occupy a mark slot
ANNOTATION_RE = re.compile(r'^[@*]')  # e.g. '@2', '*1', '**5' attempt-number annotations - ignore, don't consume a slot

def cluster_lines(words, tol=3.0):
    """Group words into visual lines by 'top' proximity."""
    words = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines = []
    cur = []
    cur_top = None
    for w in words:
        if cur_top is None or abs(w['top'] - cur_top) <= tol:
            cur.append(w)
            cur_top = w['top'] if cur_top is None else cur_top
        else:
            lines.append(cur)
            cur = [w]
            cur_top = w['top']
    if cur:
        lines.append(cur)
    return lines

def parse_subject_slots(tokens):
    """tokens: list of word dicts sorted by x0, within one subcolumn region of one line.
    Returns list of (subject_code, ext, intr, gp, grade)."""
    slots = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]['text']
        if SUBJECT_RE.match(t):
            code = t
            i += 1
            # optional status marker
            if i < n and STATUS_RE.match(tokens[i]['text']):
                i += 1
            nums = []
            # collect following tokens until we hit next subject code or run out
            while i < n and not SUBJECT_RE.match(tokens[i]['text']):
                tx = tokens[i]['text']
                if NUM_RE.match(tx):
                    nums.append(tx)
                    i += 1
                elif PLACEHOLDER_RE.match(tx):
                    # 'AA'/'AB'/etc are ambiguous: they can be an absent/withheld
                    # placeholder occupying a numeric mark slot (e.g. Ext missing),
                    # OR they can simply be the terminal grade letter for this slot
                    # (some CBCS grading scales use 'AA'/'AB' as top grades, GP 10/9).
                    # Disambiguate by lookahead: if a numeric mark still follows,
                    # this token is a placeholder mark; otherwise it's the grade
                    # and marks collection stops here.
                    nxt = tokens[i + 1]['text'] if i + 1 < n else None
                    if nxt is not None and NUM_RE.match(nxt):
                        nums.append(tx)
                        i += 1
                    else:
                        i += 1
                        break
                elif ANNOTATION_RE.match(tx):
                    # attempt-number annotation like '@2' - ignore, doesn't occupy a slot
                    i += 1
                else:
                    # this is the grade token (e.g. 'A+', 'O', 'F') - stop collecting marks
                    i += 1
                    break
            gp = nums[-1] if nums else None
            marks = nums[:-1] if len(nums) >= 1 else []
            ext = marks[0] if len(marks) >= 1 else None
            intr = marks[1] if len(marks) >= 2 else None
            slots.append((code, ext, intr, gp))
        else:
            i += 1
    return slots

def parse_page(words):
    """Return list of record dicts for one page."""
    lines = cluster_lines(words)
    # find line indices where a line starts a new record (has ENROLL match)
    record_starts = []
    for idx, line in enumerate(lines):
        for w in line:
            if ENROLL_RE.match(w['text']):
                record_starts.append(idx)
                break
    records = []
    for ri, start_idx in enumerate(record_starts):
        end_idx = record_starts[ri+1] if ri+1 < len(record_starts) else len(lines)
        rec_lines = lines[start_idx:end_idx]
        # cap runaway ranges (e.g. last record on page bleeding into legend text)
        top0 = None
        capped = []
        for line in rec_lines:
            if not line:
                continue
            if top0 is None:
                top0 = line[0]['top']
            if line[0]['top'] - top0 <= 165:
                capped.append(line)
        rec_lines = capped
        rec = {
            'enroll_no': None, 'name_parts': [], 'mother_name': None,
            'sex': None, 'medium': None, 'aggr_marks': None, 'result': None,
            'sgpa': None, 'total_credit': None, 'subjects': []  # list of (code,ext,int,gp)
        }
        rec_top0 = None
        name_cont = None
        for li, line in enumerate(rec_lines):
            # 240 (not 250) keeps a safety margin: genuine name/mother-name text never
            # extends past ~210px, while the first subject column's values can start as
            # early as ~247px in some TR templates - 250 was cutting it too close and
            # occasionally misclassified a Sub1 value as left-track name text.
            left_tokens = sorted([w for w in line if w['x0'] < 240], key=lambda w: w['x0'])
            right_tokens = sorted([w for w in line if w['x0'] >= 240], key=lambda w: w['x0'])

            if li == 0 and left_tokens:
                rec_top0 = left_tokens[0]['top']

            # --- LEFT TRACK: classify by fixed offset from record start ---
            offset = (line[0]['top'] - rec_top0) if (rec_top0 is not None and line) else None

            if li == 0:
                for w in left_tokens:
                    if ENROLL_RE.match(w['text']):
                        rec['enroll_no'] = w['text']
                    else:
                        rec['name_parts'].append(w['text'])
            elif left_tokens and offset is not None:
                texts = [w['text'] for w in left_tokens]
                if abs(offset - 11.1) <= 7:
                    # name continuation (surname)
                    name_cont = ' '.join(texts)
                elif abs(offset - 29.0) <= 7:
                    # mother's name (always present at this fixed slot). Some records
                    # show a stray alternate/old enrollment-number token before the
                    # actual name (e.g. "233870394 VIDHYA") - drop pure-numeric tokens.
                    name_only = [t for t in texts if not NUM_RE.match(t)]
                    rec['mother_name'] = ' '.join(name_only) if name_only else ' '.join(texts)
                elif abs(offset - 57.0) <= 7:
                    # Cen / CatClg / Med / Sex row, format like: 387 0 387 E F
                    # A "Withheld" result marker (W/E, W/C, W/A, W/O, W/T, W/U, W/G, W/N -
                    # defined as such in the TR's own legend key) can spill onto this same
                    # line in some templates. It is never a real Sex/Medium value, so it's
                    # filtered out before picking the trailing [Medium, Sex] tokens.
                    alpha_tokens = [
                        t for t in texts
                        if not NUM_RE.match(t) and not re.match(r'^W/[A-Z]$', t)
                    ]
                    if len(alpha_tokens) >= 2:
                        rec['medium'] = alpha_tokens[-2]
                        rec['sex'] = alpha_tokens[-1]
                    elif len(alpha_tokens) == 1:
                        rec['sex'] = alpha_tokens[-1]
                # offsets ~70.8 (remarks) and ~91.1 (previous sem marks) are ignored

            # --- RIGHT TRACK ---
            if right_tokens:
                # split into subject col A, col B, far right (aggregate/result/SGPA).
                # The far-right boundary varies a few px between TR templates (890-910),
                # so 890 is used to stay clear of col B's rightmost grade letters (~x871)
                # while still catching an aggregate-marks value as low as x~902.
                colA = [w for w in right_tokens if w['x0'] < 580]
                colB = [w for w in right_tokens if 580 <= w['x0'] < 890]
                colC = [w for w in right_tokens if w['x0'] >= 890]

                rec['subjects'].extend(parse_subject_slots(colA))
                rec['subjects'].extend(parse_subject_slots(colB))

                if li == 0 and colC:
                    # AggrTotal marks then Result text
                    nums = [w['text'] for w in colC if NUM_RE.match(w['text'])]
                    alphas = [w['text'] for w in colC if not NUM_RE.match(w['text'])]
                    if nums:
                        rec['aggr_marks'] = nums[0]
                    if alphas:
                        rec['result'] = ' '.join(alphas)

                # SGPA detection anywhere in right track. Two template styles seen:
                #  (a) an explicit "SGPA - 8.68" label+value pair, or
                #  (b) a single combined token "8.045/22" = SGPA "/" total credits,
                #      with no literal "SGPA" label printed per record at all.
                texts_right = [w['text'] for w in right_tokens]
                if 'SGPA' in texts_right:
                    si = texts_right.index('SGPA')
                    rest = texts_right[si+1:]
                    for t in rest:
                        t2 = t.lstrip('-').strip()
                        if re.match(r'^\d+\.\d+$', t2):
                            rec['sgpa'] = t2
                            break
                else:
                    for w in right_tokens:
                        m = re.match(r'^(\d+\.\d+)/(\d+)$', w['text'])
                        if m and w['x0'] >= 890:
                            rec['sgpa'] = m.group(1)
                            if not rec.get('total_credit'):
                                rec['total_credit'] = m.group(2)
                            break

                # Credit summary line pattern like 22+0+0 = 22 (appears combined as tokens: '22+0+0','=','22')
                for w in right_tokens:
                    if re.match(r'^\d+\+\d+\+\d+$', w['text']):
                        idx_ = right_tokens.index(w)
                        # find next numeric token after '='
                        for w2 in right_tokens[idx_+1:]:
                            if NUM_RE.match(w2['text']):
                                rec['total_credit'] = w2['text']
                                break
                        break

        # assemble full name
        full_name = ' '.join(rec['name_parts'])
        if name_cont:
            full_name = (full_name + ' ' + name_cont).strip()
        rec['name'] = re.sub(r'\s+', ' ', full_name).strip()
        if rec['enroll_no']:
            records.append(rec)
    return records

def extract_header_meta(page):
    """Pull college name, exam title and the 'Out Of' total from a page header."""
    text = page.extract_text() or ""
    meta = {}
    m = re.search(r'College Code & Name\s*:\s*-?\s*\d*\s*-?\s*(.+)', text)
    if m:
        meta['college'] = m.group(1).split('\n')[0].strip()
    m2 = re.search(r'((?:FOUR|THREE|TWO|ONE) YEAR|B\.?E\.?|DIPLOMA)[^\n]*SEMESTER[^\n]*', text, re.IGNORECASE)
    if m2:
        title = re.sub(r'\s+', ' ', m2.group(0)).strip()
        title = re.sub(r'\s*Page\s*No[:\s].*$', '', title, flags=re.IGNORECASE).strip()
        meta['exam_title'] = title
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    for w in words:
        if 130 <= w['top'] <= 165 and 895 <= w['x0'] <= 935 and NUM_RE.match(w['text']):
            meta['out_of'] = w['text']
            break
    return meta

def parse_pdf(path, progress_cb=None):
    all_records = []
    subject_legend = {}
    out_of_votes = Counter()
    doc_meta = {}
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for pi, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            recs = parse_page(words)
            all_records.extend(recs)

            # --- Subject legend: only harvest from the paragraph BELOW the last
            # student record on this page (course-name key at the page footer),
            # never from inside a record's own mark data. Parsed token-by-token
            # (not by regex-over-joined-text) so it works whether or not the
            # legend uses commas to separate entries - some TR templates don't. ---
            enroll_tops = [w['top'] for w in words if ENROLL_RE.match(w['text'])]
            cutoff = max(enroll_tops) + 165 if enroll_tops else 1e9
            legend_words = sorted(
                [w for w in words if w['top'] > cutoff], key=lambda w: (w['top'], w['x0'])
            )
            cur_code, cur_name_tokens = None, []
            for w in legend_words:
                tok = w['text']
                if SUBJECT_RE.match(tok):
                    if cur_code and cur_name_tokens:
                        nm = ' '.join(cur_name_tokens).strip(' ,')
                        if cur_code not in subject_legend and len(nm) > 2:
                            subject_legend[cur_code] = nm
                    cur_code, cur_name_tokens = tok, []
                elif cur_code is not None:
                    cur_name_tokens.append(tok.strip(','))
            if cur_code and cur_name_tokens:
                nm = ' '.join(cur_name_tokens).strip(' ,')
                if cur_code not in subject_legend and len(nm) > 2:
                    subject_legend[cur_code] = nm

            meta = extract_header_meta(page)
            if 'out_of' in meta:
                out_of_votes[meta['out_of']] += 1
            if pi == 0:
                doc_meta.update({k: v for k, v in meta.items() if k != 'out_of'})
            if progress_cb:
                progress_cb(pi + 1, n)
    doc_meta['out_of'] = int(out_of_votes.most_common(1)[0][0]) if out_of_votes else 750
    return all_records, subject_legend, doc_meta


def resolve_subject_name(code, subject_legend):
    """Look up a subject's display name, tolerating body/legend code mismatches.

    Some TR templates print the body-table subject code WITHOUT its trailing
    course-type suffix that the footer legend includes (e.g. body shows
    "4EP209", legend key is "4EP209PC"). Try an exact match first; if that
    fails, fall back to the legend key that the code is an unambiguous
    prefix of. Never guess if more than one legend key could match.
    """
    if code in subject_legend:
        return subject_legend[code]
    candidates = [k for k in subject_legend if k != code and k.startswith(code)]
    if len(candidates) == 1:
        return subject_legend[candidates[0]]
    return code


def records_to_rows(records, subject_legend, out_of=750):
    """Build the wide 'Marks Data' table (list of dict rows) + ordered subject code list,
    matching the target schema: fixed columns + 3 sub-columns (Ext, Int, G.P.) per subject."""
    # Preserve first-seen order of subject codes across all records
    subject_order = []
    seen = set()
    for r in records:
        for code, *_ in r['subjects']:
            if code not in seen:
                seen.add(code)
                subject_order.append(code)

    def to_num(v):
        if v in (None, ''):
            return None
        try:
            if '.' in str(v):
                return float(v)
            return int(v)
        except ValueError:
            return v  # keep placeholders like 'AA' as text

    rows = []
    for i, r in enumerate(records, start=1):
        row = {
            'S.No': i,
            'Enrollment No': r['enroll_no'],
            'Name of Candidate': r['name'],
            "Mother's Name": r['mother_name'],
            'Sex': r['sex'],
            'Medium': r['medium'],
            'Marks Obtained': to_num(r['aggr_marks']),
            'Out Of': out_of,
            'Result': r['result'],
            'SGPA': to_num(r['sgpa']),
            'Total Credit Earned': to_num(r['total_credit']),
        }
        subj_map = {code: (e, ii, g) for code, e, ii, g in r['subjects']}
        for code in subject_order:
            e, ii, g = subj_map.get(code, (None, None, None))
            subj_name = resolve_subject_name(code, subject_legend)
            row[f'{code}__Ext'] = to_num(e)
            row[f'{code}__Int'] = to_num(ii)
            row[f'{code}__GP'] = to_num(g)
        rows.append(row)
    return rows, subject_order


def build_workbook(rows, subject_order, subject_legend, out_path, meta=None):
    """Write the parsed data to an .xlsx workbook with 'Marks Data' + 'Subject Legend'
    sheets, matching the SGBAU TR conversion schema (fixed columns + Ext/Int/G.P. per subject)."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Marks Data'

    fixed_cols = ['S.No', 'Enrollment No', 'Name of Candidate', "Mother's Name", 'Sex',
                  'Medium', 'Marks Obtained', 'Out Of', 'Result', 'SGPA', 'Total Credit Earned']

    header_fill = PatternFill('solid', fgColor='1F4E78')
    subhead_fill = PatternFill('solid', fgColor='2E75B6')
    header_font = Font(color='FFFFFF', bold=True)
    thin = Side(style='thin', color='B7C6D9')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # --- header rows (3-row merged header, matching reference layout) ---
    col = 1
    for name in fixed_cols:
        ws.cell(row=1, column=col, value=name)
        ws.merge_cells(start_row=1, start_column=col, end_row=3, end_column=col)
        col += 1
    subj_start_col = col
    for code in subject_order:
        subj_name = resolve_subject_name(code, subject_legend)
        ws.cell(row=1, column=col, value=subj_name)
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + 2)
        ws.cell(row=2, column=col, value=code)
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 2)
        ws.cell(row=3, column=col, value='Ext')
        ws.cell(row=3, column=col + 1, value='Int')
        ws.cell(row=3, column=col + 2, value='G.P.')
        col += 3

    for r in range(1, 4):
        for c in range(1, col):
            cell = ws.cell(row=r, column=c)
            cell.font = header_font
            cell.alignment = center
            cell.fill = header_fill if r == 1 else subhead_fill
            cell.border = border

    # --- data rows ---
    all_cols = fixed_cols[:]
    for code in subject_order:
        all_cols += [f'{code}__Ext', f'{code}__Int', f'{code}__GP']

    for ri, row in enumerate(rows, start=4):
        for ci, key in enumerate(all_cols, start=1):
            val = row.get(key)
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.border = border
            if key in ('Result',) and val:
                cell.font = Font(bold=True, color='C00000' if val != 'PASS' else '006100')

    # column widths
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 30
    ws.column_dimensions['D'].width = 18
    for i in range(5, col):
        ws.column_dimensions[get_column_letter(i)].width = 9
    ws.freeze_panes = 'E4'

    # --- Subject Legend sheet ---
    ws2 = wb.create_sheet('Subject Legend')
    ws2.append(['Subject Code', 'Subject Name'])
    for c in ws2[1]:
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
    for code in subject_order:
        ws2.append([code, resolve_subject_name(code, subject_legend)])
    ws2.column_dimensions['A'].width = 16
    ws2.column_dimensions['B'].width = 50

    # --- Summary sheet ---
    ws3 = wb.create_sheet('Summary')
    total = len(rows)
    passed = sum(1 for r in rows if r.get('Result') == 'PASS')
    failed = total - passed
    sgpas = [r['SGPA'] for r in rows if isinstance(r.get('SGPA'), (int, float))]
    avg_sgpa = round(sum(sgpas) / len(sgpas), 2) if sgpas else None
    summary_data = [
        ('College', (meta or {}).get('college', '')),
        ('Exam', (meta or {}).get('exam_title', '')),
        ('Total Students', total),
        ('Passed', passed),
        ('Failed', failed),
        ('Pass %', round(100 * passed / total, 2) if total else 0),
        ('Average SGPA (passed students)', avg_sgpa),
        ('Total Subjects', len(subject_order)),
    ]
    ws3.append(['Metric', 'Value'])
    for c in ws3[1]:
        c.font = header_font
        c.fill = header_fill
    for k, v in summary_data:
        ws3.append([k, v])
    ws3.column_dimensions['A'].width = 32
    ws3.column_dimensions['B'].width = 40

    wb.save(out_path)
    return out_path
