#!/usr/bin/env python3
from scoped_host_export_routes import FLAT_HOST_EXPORT_ROUTES, PACKED_FRONTEND_EXPORT_ROUTES
from scoped_host_exports import ScopedExportIndex, scoped_host_export_aliases, scoped_host_export_original

N1_HOST_REQUIRED = frozenset((
    "checked_program_intern",
    "checked_program_type_globals_indexed",
    "codegen_checked",
    "fs_error_message",
    "lower_recheck_program",
    "managed_driver_error",
    "managed_driver_source_error",
    "managed_finish_plan",
    "managed_lower_raw_part",
    "managed_plan_contracts",
    "managed_prepare_rechecked",
    "mir_check_program",
    "mir_gc_annotate",
    "mir_gc_check",
    "mir_gc_infer",
    "native_build_fuel",
    "native_build_publish_checked",
    "native_scalar_lower_checked",
    "normalize_checked_indexed",
    "source_lookup_id",
))

FHS_REQUIRED = frozenset((
    "check_environment_from_entries",
    "check_indexed_declaration",
    "check_indexed_module_with",
    "check_module",
    "checked_program_entries",
    "checked_program_intern",
    "checked_program_type_globals_indexed",
    "codegen_assemble",
    "codegen_block",
    "codegen_body",
    "codegen_checked",
    "codegen_clear_dead_roots",
    "codegen_prepare_begin",
    "codegen_prepare_step",
    "codegen_program",
    "codegen_runtime_budget_offset",
    "codegen_runtime_descriptors",
    "compile_checked_source",
    "compile_checked_units",
    "compile_program",
    "desugar_file",
    "driver_elaborate_surfaces",
    "driver_parse_file_visibility",
    "elaborate",
    "file_item_name",
    "frontend_host_file_status_parts",
    "fs_error_message",
    "lex_go_import",
    "live_runtime_calls",
    "live_runtime_pap_plateau",
    "live_runtime_reclaim",
    "lower_expr_env2",
    "lower_find_entry",
    "lower_make_contract_indexed",
    "lower_normalize",
    "lower_recheck_program",
    "managed_driver_error",
    "managed_driver_source_error",
    "managed_finish_plan",
    "managed_fixture_runtime_with_limits",
    "managed_lower_raw_part",
    "managed_plan_contracts",
    "managed_prepare_rechecked",
    "managed_source_spelling",
    "managed_source_symbol",
    "managed_source_symbol_using",
    "managed_validate_parts",
    "managed_value_escape_collect",
    "managed_value_pap_collect",
    "mir_check_declared_flow",
    "mir_check_function",
    "mir_check_function_with",
    "mir_check_program",
    "mir_gc_annotate",
    "mir_gc_check",
    "mir_gc_infer",
    "mir_global_ids",
    "mir_live_roots",
    "mir_managed_descriptors",
    "mir_reachable",
    "mir_reachable_with",
    "native_build_fuel",
    "native_build_load_source",
    "native_build_normalize",
    "native_build_publish_checked",
    "native_build_publish_image",
    "native_file_read_status_fixture",
    "native_scalar_lower_checked",
    "normalize_checked_indexed",
    "pe_apply_patches",
    "pe_cached_section_lookup",
    "pe_check_bytes",
    "pe_function_scan",
    "pe_patch_prefix",
    "pe_patch_prefix_step",
    "pe_resolve_fixup_indexed_with",
    "pe_run_byte_check",
    "pe_run_fixup_step",
    "pe_symbol_index_from_symbols",
    "pe_word32",
    "pipeline_compile_checked_source",
    "preprocess_imports_reg",
    "preprocess_records_reg",
    "rewrite_declarations",
    "source_lookup_id",
))

FLAT_FRONTEND_REQUIRED = frozenset(
    {"elaborate_surfaces": "driver_elaborate_surfaces", "elaborate_fuel": "elaborate"}.get(alias, alias)
    for _module, alias, _name, _owners in PACKED_FRONTEND_EXPORT_ROUTES
)
MODULE_SCOPE_NAMES = frozenset((
    "module_members", "module_owned_exports", "module_shadow_exports", "module_unique_exports",
    "module_rewrite_unit_pure", "module_maps_for", "module_scope_maps", "module_bare_ctors",
    "module_rewrite_decls_with_opens_pure", "module_rewrite_decl_pure", "module_invalid_maps",
    "source_name_compare_scope",
    "elem_scope",
    "module_maps_for_cached_pure", "module_rewrite_unit_cached_pure",
))
PACKED_ROOTS = {
    "_lx": "compiler/lexer.ouro", "_pa": "compiler/parse_a.ouro", "_pb": "compiler/parse_b.ouro",
    "_pf": "compiler/parser_file.ouro", "_ds": "compiler/desugar_match.ouro",
    "_ir": "compiler/import_resolve.ouro", "_lr": "compiler/lower_rewrite.ouro",
    "_lo": "compiler/lower.ouro", "_el": "compiler/elab.ouro", "_co": "compiler/compiler.ouro",
    "_fc": "compiler/file_elab.ouro", "_pi": "compiler/preprocess_import.ouro",
    "_pr": "compiler/preprocess_record.ouro", "_pl": "compiler/pipeline.ouro",
}


def _require_consumers(routes, required, units):
    selected = {alias: owners for alias, _name, owners in routes}
    if len(selected) != len(routes) or required - selected.keys():
        raise RuntimeError("missing or duplicate closed consumer route")
    for alias in sorted(required):
        if sum(owner in units for owner in selected[alias]) != 1:
            raise RuntimeError(f"missing or ambiguous mandatory consumer owner {alias}")


def current_native_scoped_aliases(text, units, canonical_units, entry, sources, *, installed=False,
                                  export_index: ScopedExportIndex | None = None):
    required = {
        "tools/native_build.ouro": FLAT_FRONTEND_REQUIRED | N1_HOST_REQUIRED,
        "tests/frontend_host_codegen.ouro": FLAT_FRONTEND_REQUIRED | FHS_REQUIRED,
    }.get(entry, frozenset())
    _require_consumers(FLAT_HOST_EXPORT_ROUTES, required, units)
    return scoped_host_export_aliases(text, units, canonical_units, entry, sources,
                                      FLAT_HOST_EXPORT_ROUTES, installed=installed, export_index=export_index)


def current_native_scoped_original(text, units, canonical_units, entry, sources, *,
                                   export_index: ScopedExportIndex | None = None):
    required = {
        "tools/native_build.ouro": FLAT_FRONTEND_REQUIRED | N1_HOST_REQUIRED,
        "tests/frontend_host_codegen.ouro": FLAT_FRONTEND_REQUIRED | FHS_REQUIRED,
    }.get(entry, frozenset())
    _require_consumers(FLAT_HOST_EXPORT_ROUTES, required, units)
    return scoped_host_export_original(text, units, canonical_units, entry, sources,
                                       FLAT_HOST_EXPORT_ROUTES, export_index=export_index)


def _packed_routes(module, entry, units):
    if PACKED_ROOTS.get(module) != entry:
        raise RuntimeError("wrong closed frontend suffix or source entry")
    routes = [(alias, name, owners) for suffix, alias, name, owners in PACKED_FRONTEND_EXPORT_ROUTES
              if suffix == module]
    required = frozenset(alias for alias, _name, _owners in routes)
    known = {alias for alias, _name, _owners in routes}
    routes.extend(row for row in FLAT_HOST_EXPORT_ROUTES if row[0] in MODULE_SCOPE_NAMES and row[0] not in known)
    _require_consumers(routes, required, units)
    return routes


def current_packed_scoped_aliases(text, units, canonical_units, entry, sources, module, *, installed=False,
                                  export_index: ScopedExportIndex | None = None):
    routes = _packed_routes(module, entry, units)
    return scoped_host_export_aliases(text, units, canonical_units, entry, sources,
                                      routes, module, installed=installed, export_index=export_index)


def current_packed_scoped_original(text, units, canonical_units, entry, sources, module, *,
                                   export_index: ScopedExportIndex | None = None):
    routes = _packed_routes(module, entry, units)
    return scoped_host_export_original(text, units, canonical_units, entry, sources, routes, module,
                                       export_index=export_index)
