# -*- coding: utf-8 -*-
"""nianpu_core：年譜處理核心包（由單檔 nianpu_processor.py 機械拆分而來）。

模塊依賴方向（單向，無循環）：
  constants ← base ← expand ← preprocess ← anchors ← fixes ← modern
                                  ← patterns ← verify ← process ← cli
"""
import sys
from pathlib import Path

# 保證 slot_model / cbdb 等技能根目錄模塊在任意導入方式下可達
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from .constants import (
    SKILL_DIR, LEARNINGS_FILE,
    REIGNS, EMPEROR_PREFIXES, PERSON_PREFIXES,
    AGE_SUFFIXES, AGE_SUFFIX_REQUIRED, AGE_DIGITS,
    REIGN_START_YEARS, REIGN_END_YEARS,
    _CN_NUM, _TG, _DZ, STEM_BRANCH,
    SEASON_MARKERS, _SEASON_EXCLUDE_CONTINUATION, _SEASONS, _SEASON_MONTHS,
    EVENT_MARKERS,
    _STEMS_CANON, _BRANCHES_CANON, _STEM_IDX, _BRANCH_IDX, _GANZHI_INDEX,
    _REIGN_SERIES, _OCR_FIXES, _REIGN_NORMALIZATIONS, _QING_REIGNS,
)
from .base import (
    _chinese_year_to_int, _chinese_digits_to_int, _compute_ad_year,
    _ganzhi_index_of_pair, _ganzhi_pair_of_ad, _int_to_chinese_year,
    _build_year_pattern, extract_reign, _gz_age_connector, detect_person_prefixes,
)
from .expand import (
    _expand_bare_gz_heading, _reign_dynasty, _ad_to_reign,
    _find_gz_age_birth_ref, _inject_birth_ganzhi,
    _expand_gz_age_heading, _expand_pure_age_heading, _reign_label_of_ad,
)
from .preprocess import (
    _apply_ocr_fixes, _normalize_reign_variants, _split_embedded_years,
    _dedupe_repeated_year_headings, _fill_missing_bare_year_title,
    _next_nonempty, _merge_multi_line_years, _make_heading, _merge_broken_lines,
)
from .anchors import _parse_heading_anchors, _consensus_birth_year, verify_anchors
from .fixes import (
    _reign_span, reign_for_year, suggest_fix, apply_fixes,
    _anchor_fix_check, _cbdb_check, get_person, _cbdb_extract_name,
)
from .modern import (
    _parse_modern_components, try_parse_modern_heading,
    _normalize_modern_heading, check_modern_headers, process_modern_nianpu,
)
from .patterns import classify_format, _build_full_pattern
from .segment import (
    split_by_month, _build_all_labels, _is_season_compound, _process_year_content,
)
from .learnings import (
    _learnings_path, _load_learnings, _save_learnings,
    _is_valid_reign_candidate, _compute_reign_confidence, _discover_reigns,
    _is_valid_prefix_candidate, _discover_prefixes,
    _is_valid_suffix_candidate, _discover_age_suffixes,
    self_learn, _record_correction, _accumulate_ocr_candidate,
    record_manual_correction, prune_invalidated_learnings,
    apply_learnings, print_learnings_summary,
)
from .verify import verify_output, _format_anchor_report
from .process import annotate_ad_years, process_nianpu, slots_to_fmt
from .cli import main

__all__ = [
    # constants
    'SKILL_DIR', 'LEARNINGS_FILE', 'REIGNS', 'EMPEROR_PREFIXES', 'PERSON_PREFIXES',
    'AGE_SUFFIXES', 'AGE_SUFFIX_REQUIRED', 'AGE_DIGITS',
    'REIGN_START_YEARS', 'REIGN_END_YEARS', '_CN_NUM', '_TG', '_DZ', 'STEM_BRANCH',
    'SEASON_MARKERS', '_SEASON_EXCLUDE_CONTINUATION', '_SEASONS', '_SEASON_MONTHS',
    'EVENT_MARKERS', '_STEMS_CANON', '_BRANCHES_CANON', '_STEM_IDX', '_BRANCH_IDX',
    '_GANZHI_INDEX', '_REIGN_SERIES', '_OCR_FIXES', '_REIGN_NORMALIZATIONS',
    '_QING_REIGNS',
    # base
    '_chinese_year_to_int', '_chinese_digits_to_int', '_compute_ad_year',
    '_ganzhi_index_of_pair', '_ganzhi_pair_of_ad', '_int_to_chinese_year',
    '_build_year_pattern', 'extract_reign', '_gz_age_connector', 'detect_person_prefixes',
    # expand
    '_expand_bare_gz_heading', '_reign_dynasty', '_ad_to_reign',
    '_find_gz_age_birth_ref', '_inject_birth_ganzhi',
    '_expand_gz_age_heading', '_expand_pure_age_heading', '_reign_label_of_ad',
    # preprocess
    '_apply_ocr_fixes', '_normalize_reign_variants', '_split_embedded_years',
    '_dedupe_repeated_year_headings', '_fill_missing_bare_year_title',
    '_next_nonempty', '_merge_multi_line_years', '_make_heading', '_merge_broken_lines',
    # anchors
    '_parse_heading_anchors', '_consensus_birth_year', 'verify_anchors',
    # fixes
    '_reign_span', 'reign_for_year', 'suggest_fix', 'apply_fixes',
    '_anchor_fix_check', '_cbdb_check', 'get_person', '_cbdb_extract_name',
    # modern
    '_parse_modern_components', 'try_parse_modern_heading',
    '_normalize_modern_heading', 'check_modern_headers', 'process_modern_nianpu',
    # patterns
    'classify_format', '_build_full_pattern',
    # segment
    'split_by_month', '_build_all_labels', '_is_season_compound', '_process_year_content',
    # learnings
    '_learnings_path', '_load_learnings', '_save_learnings',
    '_is_valid_reign_candidate', '_compute_reign_confidence', '_discover_reigns',
    '_is_valid_prefix_candidate', '_discover_prefixes',
    '_is_valid_suffix_candidate', '_discover_age_suffixes',
    'self_learn', '_record_correction', '_accumulate_ocr_candidate',
    'record_manual_correction', 'prune_invalidated_learnings',
    'apply_learnings', 'print_learnings_summary',
    # verify
    'verify_output', '_format_anchor_report',
    # process
    'annotate_ad_years', 'process_nianpu', 'slots_to_fmt',
    # cli
    'main',
]
