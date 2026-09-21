#!/usr/bin/env python3
"""Public launcher and compatibility re-exports for the structural quality pass.

The live implementation lives in scripts/structural_quality_legacy.py, the
import-only lex/extraction oracle compared by scripts/structural_lex_parity.py.
This module keeps the public names used by the firewall, suite, and other host
callers.
"""
from __future__ import annotations

import structural_quality_legacy as _impl
from structural_quality_legacy import (
    CATEGORIES,
    CONTROL,
    IDENT,
    KIND,
    MARKER,
    OPERATORS,
    PURPOSES,
    RESERVED,
    RULES,
    SOURCE_SUFFIXES,
    SPECIAL_RULES,
    WORD,
    Symbol,
    Token,
    analyze,
    ast_name,
    binders,
    boundaries,
    call_names,
    classify,
    clone_findings,
    dead_findings,
    digest,
    fallback_findings,
    inventory,
    lex,
    lexical_symbols,
    make_finding,
    near_findings,
    normalize,
    orphan_findings,
    owned_fingerprints,
    pairs,
    purposes,
    python_symbols,
    semantic_findings,
    surface_findings,
    symbol_index,
    unreachable_findings,
    validate_report,
    wrapper_findings,
)

__all__ = [
    "CATEGORIES",
    "CONTROL",
    "IDENT",
    "KIND",
    "MARKER",
    "OPERATORS",
    "PURPOSES",
    "RESERVED",
    "RULES",
    "SOURCE_SUFFIXES",
    "SPECIAL_RULES",
    "WORD",
    "Symbol",
    "Token",
    "analyze",
    "ast_name",
    "binders",
    "boundaries",
    "call_names",
    "classify",
    "clone_findings",
    "dead_findings",
    "digest",
    "fallback_findings",
    "inventory",
    "lex",
    "lexical_symbols",
    "make_finding",
    "near_findings",
    "normalize",
    "orphan_findings",
    "owned_fingerprints",
    "pairs",
    "purposes",
    "python_symbols",
    "run",
    "semantic_findings",
    "surface_findings",
    "symbol_index",
    "unreachable_findings",
    "validate_report",
    "wrapper_findings",
]


def run(root, report_path):
    """Publish a structural report through the live oracle implementation."""
    return _impl.run(root, report_path)
