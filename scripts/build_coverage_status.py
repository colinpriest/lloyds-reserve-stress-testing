"""Build the syndicate-year coverage status table and reconciliation reports.

Joins, for every syndicate-year in syndicate_reports/Lloyds_syndicates_2014_2024.xlsx:
  a) download status            (syndicate_reports/download_status.json)
  b) PYD incurred development   (pdf_extraction/syndicate_{s}_{y}.json)
  c) gross LoB mix              (pdf_extraction/syndicate_{s}_{y}.json)
  d) gross opening claims reserves (pdf_extraction/syndicate_{s}_{y}.json)
  e) RITC occurrence            (pdf_extraction/ritc_scan.json)

Each extracted value carries the name of the table/section it was sourced
from: deterministic table provenance (claims development triangle, segmental
analysis) is resolved to a page + heading via the Azure table cache and a
heading scan of the PDF page; LLM-sourced values use the page number the LLM
reported, resolved the same way.

Full success for a syndicate-year = (a) downloaded AND (b) PYD extracted AND
(c) LoB mix extracted AND (d) opening reserves extracted. RITC is reported
but not part of the full-success definition.

Outputs (in syndicate_reports/coverage/):
  coverage_status.xlsx     one row per syndicate-year (+ by-year, by-syndicate,
                           reconciliation sheets)
  coverage_status.json     full detail including LoB mixes and evidence
  coverage_report.md       human-readable summary with reconciliation waterfall

Usage:
    python scripts/build_coverage_status.py
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = PROJECT_ROOT / "syndicate_reports" / "Lloyds_syndicates_2014_2024.xlsx"
PDF_DIR = PROJECT_ROOT / "syndicate_reports" / "pdfs"
DOWNLOAD_STATUS_PATH = PROJECT_ROOT / "syndicate_reports" / "download_status.json"
EXTRACTION_DIR = PROJECT_ROOT / "pdf_extraction"
AZURE_DIR = EXTRACTION_DIR / "azure_output"
RITC_SCAN_PATH = EXTRACTION_DIR / "ritc_scan.json"
OUT_DIR = PROJECT_ROOT / "syndicate_reports" / "coverage"

# Tolerances from the extraction spec (README): PYD +/-2.0m or +/-5%,
# opening reserves +/-5%.
PYD_ABS_TOL = 2.0
PYD_REL_TOL = 0.05
RESERVES_REL_TOL = 0.05

logger = logging.getLogger(__name__)

_DANGLING_ENDINGS = (
    'the', 'a', 'an', 'of', 'for', 'and', 'or', 'to', 'in', 'on', 'by',
    'with', 'from', 'as', 'at', 'is', 'are', 'was', 'were', 'its',
)


def _looks_like_heading(line: str) -> bool:
    if re.match(r'^(note\s+\d+\b|\d{1,2}[\.\)]\s+[A-Z])', line, re.I):
        return True
    if len(line) > 70:
        return False
    words = line.split()
    if not words or len(words) > 8:
        return False
    if words[-1].lower().rstrip(':,') in _DANGLING_ENDINGS:
        return False
    if line.endswith((',', ';', '-')):
        return False
    if line.upper() == line and any(c.isalpha() for c in line):
        return True
    if not line[0].isupper():
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.5


class PageHeadingResolver:
    """Resolve (report file, page number) -> section heading, with caching."""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[str, int], Optional[str]] = {}

    def heading(self, report_file: Path, page_no: Optional[int],
                keywords: Optional[List[str]] = None) -> Optional[str]:
        """Return the most plausible section heading for a page.

        If keywords are given, prefer a heading containing one of them
        anywhere on the page; otherwise the first heading-like line.
        """
        if page_no is None or not report_file.exists():
            return None
        if report_file.suffix.lower() not in ('.pdf',):
            return None
        key = (report_file.name, page_no, tuple(keywords or ()))
        if key in self._cache:
            return self._cache[key]

        heading = None
        try:
            doc = fitz.open(report_file)
            try:
                if 1 <= page_no <= len(doc):
                    text = doc[page_no - 1].get_text()
                    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
                    headings = []
                    for ln in lines[:60]:
                        if re.fullmatch(r'[\d,.\s()%£$€-]+', ln):
                            continue
                        low = ln.lower()
                        if low.startswith(('syndicate ', 'annual report',
                                           'annual accounts', 'report and accounts',
                                           'for the year ended', 'year ended',
                                           'notes to the')):
                            continue
                        if _looks_like_heading(ln):
                            headings.append(ln)
                    if keywords:
                        for h in headings:
                            if any(k.lower() in h.lower() for k in keywords):
                                heading = h
                                break
                    if heading is None and headings:
                        heading = headings[0]
            finally:
                doc.close()
        except Exception as e:
            logger.debug(f"Heading scan failed {report_file.name} p{page_no}: {e}")
        self._cache[key] = heading
        return heading


class PageLocator:
    """Locate a table/section page in a PDF by content keywords.

    (The Azure cache's orig_page is an index into the slim page subset sent
    to the API, not the original document page, so pages are re-located here
    directly from the PDF text.)
    """

    def __init__(self) -> None:
        self._text_cache: Dict[str, List[str]] = {}

    def _pages(self, report_file: Path) -> List[str]:
        if report_file.name not in self._text_cache:
            pages: List[str] = []
            if report_file.suffix.lower() == '.pdf':
                try:
                    doc = fitz.open(report_file)
                    try:
                        pages = [p.get_text() for p in doc]
                    finally:
                        doc.close()
                except Exception as e:
                    logger.debug(f"Text extraction failed {report_file.name}: {e}")
            self._text_cache[report_file.name] = pages
        return self._text_cache[report_file.name]

    def find(self, report_file: Optional[Path], required: List[str],
             preferred: Optional[List[str]] = None) -> Tuple[Optional[int], Optional[str]]:
        """Return (1-based page, heading) of the first page containing any
        `required` keyword — preferring pages that also contain a `preferred`
        keyword (e.g. 'gross'). The heading is the keyword-bearing title line
        on that page when one exists.
        """
        if report_file is None:
            return None, None
        pages = self._pages(report_file)
        matches: List[Tuple[int, str]] = []
        for i, text in enumerate(pages, start=1):
            low = text.lower()
            if any(k in low for k in required):
                matches.append((i, text))
        if not matches:
            return None, None

        def score(item: Tuple[int, str]) -> Tuple[int, int, int]:
            i, text = item
            low = text.lower()
            # Count preferred-keyword hits (e.g. the extracted LOB names):
            # the true table page contains most of them
            pref = sum(1 for p in preferred if p in low) if preferred else 0
            # Actual table pages are number-dense; narrative mentions are not
            n_numbers = len(re.findall(r'\d[\d,]{2,}', text))
            return (pref, min(n_numbers, 60), -i)

        page_no, text = max(matches, key=score)

        # Prefer the keyword-bearing title line as the heading
        heading = None
        for ln in (ln.strip() for ln in text.split('\n')):
            if not ln or len(ln) > 90:
                continue
            low = ln.lower()
            if any(k in low for k in required) and not re.search(r'\d{3,}', ln):
                heading = ln
                break
        return page_no, heading


def values_agree(a: Optional[float], b: Optional[float],
                 abs_tol: Optional[float], rel_tol: float) -> bool:
    if a is None or b is None:
        return False
    diff = abs(a - b)
    if abs_tol is not None and diff <= abs_tol:
        return True
    base = max(abs(a), abs(b))
    return base > 0 and diff / base <= rel_tol


def report_file_for(syndicate: int, year: int) -> Optional[Path]:
    for ext in ('.pdf', '.html', '.htm'):
        p = PDF_DIR / f"syndicate_{syndicate}_{year}{ext}"
        if p.exists():
            return p
    return None


def analyse_extraction(syndicate: int, year: int,
                       resolver: PageHeadingResolver,
                       locator: 'PageLocator') -> dict:
    """Derive field statuses + sources from a pdf_extraction JSON."""
    out = {
        'extraction_file_exists': False,
        'pyd_status': 'failed', 'pyd_value_gbp_m': None, 'pyd_source': None,
        'pyd_failure_reason': 'not yet extracted',
        'opening_status': 'failed', 'opening_value_gbp_m': None,
        'opening_source': None, 'opening_failure_reason': 'not yet extracted',
        'lob_status': 'failed', 'lob_mix': None, 'lob_source': None,
        'lob_n': 0, 'lob_failure_reason': 'not yet extracted',
        'exclusion_class': None,
    }
    path = EXTRACTION_DIR / f"syndicate_{syndicate}_{year}.json"
    if not path.exists():
        return out
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        out['pyd_failure_reason'] = f'extraction JSON unreadable: {e}'
        out['opening_failure_reason'] = out['pyd_failure_reason']
        out['lob_failure_reason'] = out['pyd_failure_reason']
        return out
    out['extraction_file_exists'] = True
    rpt = report_file_for(syndicate, year)

    # ---- special classifications -------------------------------------
    if data.get('first_year_syndicate'):
        reason = 'first/second-year syndicate: no prior year development possible'
        out['exclusion_class'] = 'first_year_syndicate'
        out['pyd_failure_reason'] = reason
        out['opening_failure_reason'] = reason
        mix = data.get('gross_premium_mix')
        if mix:
            out.update(_lob_from_mix(mix, syndicate, year, rpt, locator,
                                     deterministic=False))
        else:
            out['lob_failure_reason'] = 'no LOB mix in first-year audit JSON'
        return out
    if data.get('no_triangle_data') or data.get('excluded'):
        reason = data.get('exclusion_reason',
                          'no claims triangle or reserve movement text found')
        out['exclusion_class'] = 'no_triangle_data'
        out['pyd_failure_reason'] = reason
        out['opening_failure_reason'] = reason
        mix = data.get('gross_premium_mix')
        if mix:
            out.update(_lob_from_mix(mix, syndicate, year, rpt, locator,
                                     deterministic=False))
        else:
            out['lob_failure_reason'] = 'no LOB mix available (report excluded)'
        return out

    models = data.get('models', {})
    gem = next((v for k, v in models.items() if 'gemini' in k.lower()), {}) or {}
    gpt = next((v for k, v in models.items() if 'gpt' in k.lower()
                or 'openai' in k.lower()), {}) or {}
    if not isinstance(gem, dict):
        gem = {}
    if not isinstance(gpt, dict):
        gpt = {}

    # ---- PYD ----------------------------------------------------------
    rag_triangle = gem.get('_rag_triangle') or gpt.get('_rag_triangle')
    pyd_gem = gem.get('prior_year_development_gbp_m')
    pyd_gpt = gpt.get('prior_year_development_gbp_m')
    pyd_value = None
    pyd_source = None
    if rag_triangle:
        # RAG triangle is authoritative; the pipeline writes the triangle-
        # derived PYD into the model fields when it overrides.
        pyd_value = pyd_gem if pyd_gem is not None else pyd_gpt
        ttype = rag_triangle.get('type', 'gross') if isinstance(rag_triangle, dict) else 'gross'
        page, heading = locator.find(
            rpt, ['claims development', 'cumulative claims', 'years later',
                  'development of claims'],
            preferred=['gross'] if ttype == 'gross' else ['net'])
        pyd_source = (f"Claims development table ({ttype})"
                      + (f", '{heading}'" if heading else "")
                      + (f", p.{page}" if page else "")
                      + " — computed from triangle diagonals")
    elif values_agree(pyd_gem, pyd_gpt, PYD_ABS_TOL, PYD_REL_TOL):
        pyd_value = pyd_gem
        page = gem.get('prior_year_movement_page') or gpt.get('prior_year_movement_page')
        heading = resolver.heading(rpt, page, ['claims', 'provision', 'technical',
                                               'reserve']) if rpt else None
        pyd_source = ("LLM cross-validated text extraction"
                      + (f", '{heading}'" if heading else "")
                      + (f", p.{page} (LLM-cited page)" if page else ""))
    elif pyd_gem is not None or pyd_gpt is not None:
        out['pyd_failure_reason'] = (
            f'LLM disagreement unresolved (gemini={pyd_gem}, gpt={pyd_gpt}), '
            'no RAG triangle to adjudicate')
    else:
        out['pyd_failure_reason'] = 'no PYD found by triangle, provisions note, or LLM text'

    if pyd_value is not None:
        out['pyd_status'] = 'successful'
        out['pyd_value_gbp_m'] = pyd_value
        out['pyd_source'] = pyd_source
        out['pyd_failure_reason'] = None

    # ---- Opening reserves ----------------------------------------------
    op_gem = gem.get('opening_reserves_gbp_m')
    op_gpt = gpt.get('opening_reserves_gbp_m')
    op_value = None
    if values_agree(op_gem, op_gpt, None, RESERVES_REL_TOL):
        op_value = op_gem
    elif op_gem is not None and op_gpt is None:
        op_value = op_gem
    elif op_gpt is not None and op_gem is None:
        op_value = op_gpt
    if op_value is not None:
        page = gem.get('opening_reserves_page') or gpt.get('opening_reserves_page')
        heading = resolver.heading(rpt, page, ['claims outstanding', 'technical provision',
                                               'claims development', 'provision']) if rpt else None
        out['opening_status'] = 'successful'
        out['opening_value_gbp_m'] = op_value
        out['opening_source'] = ((f"'{heading}'" if heading else "Reserves note")
                                 + (f", p.{page} (LLM-cited page)" if page else ""))
        out['opening_failure_reason'] = None
    elif op_gem is not None or op_gpt is not None:
        out['opening_failure_reason'] = (
            f'LLM disagreement unresolved (gemini={op_gem}, gpt={op_gpt})')
    else:
        out['opening_failure_reason'] = 'no opening reserves figure found'

    # ---- LOB mix ---------------------------------------------------------
    adobe_lob = gem.get('_adobe_lob') or gpt.get('_adobe_lob')
    if isinstance(adobe_lob, dict) and adobe_lob.get('gross_premium_mix'):
        out.update(_lob_from_mix(adobe_lob['gross_premium_mix'], syndicate, year,
                                 rpt, locator, deterministic=True))
    else:
        mix = gem.get('gross_premium_mix') or gpt.get('gross_premium_mix')
        if mix:
            out.update(_lob_from_mix(mix, syndicate, year, rpt, locator,
                                     deterministic=False,
                                     llm_page=gem.get('gross_premium_page')
                                     or gpt.get('gross_premium_page')))
        else:
            out['lob_failure_reason'] = 'no segmental analysis table or LLM LOB mix found'
    return out


def _lob_from_mix(mix: list, syndicate: int, year: int, rpt: Optional[Path],
                  locator: 'PageLocator', deterministic: bool,
                  llm_page: Optional[int] = None) -> dict:
    if not isinstance(mix, list) or not mix:
        return {'lob_status': 'failed', 'lob_failure_reason': 'empty LOB mix'}
    # The true segmental table page contains the extracted LOB names
    lob_names = [str(e.get('line_of_business', '')).lower()
                 for e in mix if isinstance(e, dict)]
    page, heading = locator.find(
        rpt, ['segmental analysis', 'class of business', 'classes of business'],
        preferred=[n for n in lob_names if len(n) > 3])
    if page is None and llm_page is not None:
        page, heading = llm_page, None
    method = ("Segmental analysis table (deterministic table extraction)"
              if deterministic else "LLM text extraction")
    source = (method + (f", '{heading}'" if heading else "")
              + (f", p.{page}" if page else ""))
    return {
        'lob_status': 'successful',
        'lob_mix': mix,
        'lob_n': len(mix),
        'lob_source': source,
        'lob_failure_reason': None,
    }


def failure_modes(row: dict) -> List[str]:
    modes = []
    if row['download_status'] != 'report downloaded':
        modes.append('report_unavailable')
        return modes
    if row['pyd_status'] != 'successful':
        modes.append('pyd_failed')
    if row['lob_status'] != 'successful':
        modes.append('lob_failed')
    if row['opening_status'] != 'successful':
        modes.append('opening_reserves_failed')
    return modes


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(XLSX_PATH, sheet_name='All Data')
    df.columns = ['year', 'syndicate', 'agent', 'url', 'url_type']

    download_status: Dict[str, dict] = {}
    if DOWNLOAD_STATUS_PATH.exists():
        with open(DOWNLOAD_STATUS_PATH, 'r', encoding='utf-8') as f:
            download_status = json.load(f)

    ritc_scan: Dict[str, dict] = {}
    if RITC_SCAN_PATH.exists():
        with open(RITC_SCAN_PATH, 'r', encoding='utf-8') as f:
            ritc_scan = json.load(f)

    resolver = PageHeadingResolver()
    locator = PageLocator()
    rows: List[dict] = []

    for _, xrow in df.iterrows():
        syndicate = int(xrow['syndicate'])
        year = int(xrow['year'])
        key = f"{syndicate}_{year}"

        dl = download_status.get(key, {})
        rpt = report_file_for(syndicate, year)
        if rpt is not None:
            dl_status = 'report downloaded'
            dl_detail = dl.get('detail', 'already_present')
        elif dl.get('status') == 'report unavailable':
            dl_status = 'report unavailable'
            dl_detail = dl.get('detail', '')
        else:
            dl_status = 'report unavailable'
            dl_detail = 'download not yet attempted'

        row = {
            'syndicate': syndicate,
            'year': year,
            'managing_agent': xrow['agent'],
            'download_status': dl_status,
            'download_detail': dl_detail,
        }

        if dl_status == 'report downloaded':
            row.update(analyse_extraction(syndicate, year, resolver, locator))
        else:
            na = 'report unavailable'
            row.update({
                'extraction_file_exists': False,
                'pyd_status': 'failed', 'pyd_value_gbp_m': None,
                'pyd_source': None, 'pyd_failure_reason': na,
                'opening_status': 'failed', 'opening_value_gbp_m': None,
                'opening_source': None, 'opening_failure_reason': na,
                'lob_status': 'failed', 'lob_mix': None, 'lob_n': 0,
                'lob_source': None, 'lob_failure_reason': na,
                'exclusion_class': None,
            })

        ritc = ritc_scan.get(key, {})
        if ritc.get('detection') == 'successful':
            row['ritc_status'] = 'successful'
            row['ritc_occurred'] = ritc.get('ritc_occurred')
            row['ritc_confidence'] = ritc.get('confidence')
            row['ritc_source'] = (
                (ritc.get('section') or '')
                + (f", p.{ritc['page']}" if ritc.get('page') else ''))
            row['ritc_evidence'] = ritc.get('evidence')
        else:
            row['ritc_status'] = 'failed'
            row['ritc_occurred'] = None
            row['ritc_confidence'] = None
            row['ritc_source'] = None
            row['ritc_evidence'] = (ritc.get('failure_reason')
                                    if ritc else 'not scanned')

        row['failure_modes'] = ';'.join(failure_modes(row)) or None
        row['full_success'] = row['failure_modes'] is None
        rows.append(row)

    detail = pd.DataFrame(rows)

    # ---- by-year report ---------------------------------------------------
    def agg_group(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            'active_syndicate_years': len(g),
            'downloaded': int((g['download_status'] == 'report downloaded').sum()),
            'report_unavailable': int((g['download_status'] != 'report downloaded').sum()),
            'pyd_ok': int((g['pyd_status'] == 'successful').sum()),
            'lob_ok': int((g['lob_status'] == 'successful').sum()),
            'opening_ok': int((g['opening_status'] == 'successful').sum()),
            'full_success': int(g['full_success'].sum()),
            'fail_pyd': int(((g['download_status'] == 'report downloaded')
                             & (g['pyd_status'] != 'successful')).sum()),
            'fail_lob': int(((g['download_status'] == 'report downloaded')
                             & (g['lob_status'] != 'successful')).sum()),
            'fail_opening': int(((g['download_status'] == 'report downloaded')
                                 & (g['opening_status'] != 'successful')).sum()),
            'first_year_excl': int((g['exclusion_class'] == 'first_year_syndicate').sum()),
            'no_triangle_excl': int((g['exclusion_class'] == 'no_triangle_data').sum()),
            'ritc_occurred': int((g['ritc_occurred'] == True).sum()),  # noqa: E712
        })

    by_year = detail.groupby('year').apply(agg_group, include_groups=False).reset_index()
    by_synd = detail.groupby('syndicate').apply(agg_group, include_groups=False).reset_index()

    # ---- global reconciliation waterfall -----------------------------------
    total = len(detail)
    n_downloaded = int((detail['download_status'] == 'report downloaded').sum())
    n_unavailable = total - n_downloaded
    dl = detail[detail['download_status'] == 'report downloaded']
    n_first_year = int((dl['exclusion_class'] == 'first_year_syndicate').sum())
    n_no_triangle = int((dl['exclusion_class'] == 'no_triangle_data').sum())
    n_not_extracted = int((~dl['extraction_file_exists']).sum())
    analysable = dl[dl['exclusion_class'].isna() & dl['extraction_file_exists']]
    n_pyd_fail = int((analysable['pyd_status'] != 'successful').sum())
    n_full = int(detail['full_success'].sum())

    waterfall = [
        ('Syndicate-years in spreadsheet (active list)', total, None),
        ('Less: report unavailable (not published / download failed)', -n_unavailable, total - n_unavailable),
        ('Reports downloaded', None, n_downloaded),
        ('Less: not yet through extraction pipeline', -n_not_extracted, n_downloaded - n_not_extracted),
        ('Less: first/second-year syndicate (no PYD possible)', -n_first_year,
         n_downloaded - n_not_extracted - n_first_year),
        ('Less: no triangle or reserve text in report', -n_no_triangle,
         n_downloaded - n_not_extracted - n_first_year - n_no_triangle),
        ('Less: other field failures (PYD/LoB/opening not all extracted)',
         -(n_downloaded - n_not_extracted - n_first_year - n_no_triangle - n_full),
         n_full),
        ('Fully successful syndicate-years (a+b+c+d)', None, n_full),
    ]
    waterfall_df = pd.DataFrame(waterfall, columns=['step', 'change', 'running_total'])

    # ---- write outputs ------------------------------------------------------
    with open(OUT_DIR / 'coverage_status.json', 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'rows': rows,
        }, f, indent=2, ensure_ascii=False, default=str)

    xlsx_detail = detail.copy()
    xlsx_detail['lob_mix'] = xlsx_detail['lob_mix'].apply(
        lambda m: json.dumps(m, ensure_ascii=False) if isinstance(m, list) else None)
    with pd.ExcelWriter(OUT_DIR / 'coverage_status.xlsx', engine='openpyxl') as xw:
        xlsx_detail.to_excel(xw, sheet_name='syndicate_years', index=False)
        by_year.to_excel(xw, sheet_name='by_year', index=False)
        by_synd.to_excel(xw, sheet_name='by_syndicate', index=False)
        waterfall_df.to_excel(xw, sheet_name='reconciliation', index=False)

    # ---- markdown summary ----------------------------------------------------
    lines = [
        "# Syndicate-Year Coverage Report",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Global reconciliation",
        "",
        "| Step | Change | Running total |",
        "|---|---|---|",
    ]
    for step, change, running in waterfall:
        lines.append(f"| {step} | {change if change is not None else ''} "
                     f"| {running if running is not None else ''} |")
    lines += [
        "",
        "## By year (active vs full success)",
        "",
        by_year.to_markdown(index=False),
        "",
        "## Failure-mode counts by year",
        "",
        by_year[['year', 'report_unavailable', 'fail_pyd', 'fail_lob',
                 'fail_opening', 'first_year_excl', 'no_triangle_excl']]
        .to_markdown(index=False),
        "",
        "## By syndicate (top 40 by active years)",
        "",
        by_synd.sort_values(['active_syndicate_years', 'full_success'],
                            ascending=False).head(40).to_markdown(index=False),
        "",
        f"(Full by-syndicate table: coverage_status.xlsx, 'by_syndicate' sheet — "
        f"{len(by_synd)} syndicates)",
    ]
    with open(OUT_DIR / 'coverage_report.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\nRows: {total} | downloaded: {n_downloaded} | unavailable: {n_unavailable}")
    print(f"PYD ok: {int((detail['pyd_status'] == 'successful').sum())} | "
          f"LoB ok: {int((detail['lob_status'] == 'successful').sum())} | "
          f"Opening ok: {int((detail['opening_status'] == 'successful').sum())} | "
          f"RITC scanned: {int((detail['ritc_status'] == 'successful').sum())}")
    print(f"FULL SUCCESS (a+b+c+d): {n_full} / {total}")
    print(f"\nOutputs written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
