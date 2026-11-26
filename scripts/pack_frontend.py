#!/usr/bin/env python3
"""Prefix generated ouro_g/f/t/c symbols per frontend TU and concatenate.

Each --module SUFFIX blob has its own static ouro_gN table. Concatenating
without a prefix collides those statics. Sibling match-arm helpers can also
reuse the same ouro_f/t path name inside one TU; uniquify those like O8.

Type-app / ctor-field erasure belongs in extract.ouro normalize_ir.
This packer does not rewrite language IR: it only prefixes statics and
uniquifies colliding helper names. --strict dry-runs leftover detectors
and fails if extract left Type apps or extra ctor fields behind.

Runtime helpers (ouro_ctor, ouro_app, …) are left untouched. Export tables
stay ouro_export_*_SUFFIX so the C pipeline glue can look them up.

Usage:
  python3 scripts/pack_frontend.py -o compiler/stage0/driver_u.c \\
      lx:_build/fe/lx.c pa:_build/fe/pa.c ...
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from scoped_host_exports import ScopedExportIndex, _literal_prefix_matches, scoped_host_export_getters
from structural_quality_legacy import lex, pairs

if TYPE_CHECKING:
    from collections.abc import Iterable

SYM = re.compile(r"\bouro_([gftc]\d\w*)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STATIC_DEF = re.compile(
    r"static ouro_v \*([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*\{"
)
# Check the word boundary after the literal prefix so re can skip to static.
_SCOPED_STATIC_DEFINITION = re.compile(
    r"static(?<!\wstatic)\s+ouro_v\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*\{"
)
# The last number before the optional version suffix identifies the getter.
_PRELUDE_HELPER_DEFINITION = re.compile(r"ouro_[ft](?:[0-9]+_)*([0-9]+)_(?:_d[0-9]+)?")
CASE_NAME = re.compile(r'case\s+(\d+)\s*:\s*return\s+"([^"]+)"\s*;')
CASE_VAL = re.compile(
    r"case\s+(\d+)\s*:\s*return\s+(ouro_g\d+)\s*\(\s*\)\s*;"
)

# Compiled value arity after Type binders are erased.
# Source shapes (Type binders dropped):
#   bindParseResult A B r f          -> r f
#   bindValue A f r cont             -> f r cont
#   map A B f xs / append A xs ys    -> f xs / xs ys
#   isJust A m / isNothing A m       -> m
POLY_VALUE_ARITY = {
    "bindParseResult": 2,
    "bindValue": 3,
    "map": 2,
    "append": 2,
    "length": 1,
    "foldr": 3,
    "fst": 1,
    "snd": 1,
    "maybe": 3,
    "fromMaybe": 2,
    "mapMaybe": 2,
    "either": 3,
    "mapLeft": 2,
    "mapRight": 2,
    "reverse": 1,
    "filter": 2,
    "zip": 2,
    "elem": 3,
    "take": 2,
    "drop": 2,
    "isJust": 1,
    "isNothing": 1,
    "nth": 2,
}


MODULE_PURE_SCOPE_OWNER = "compiler/module_registry_base.ouro"
MODULE_PURE_SCOPE_ARITIES = (
    ("module_members", 7),
    ("module_owned_exports", 2),
    ("module_shadow_exports", 2),
    ("module_unique_exports", 1),
)
MODULE_REWRITE_UNIT_PURE_SCOPE = (
    "module_rewrite_unit_pure", 7, "compiler/module_registry.ouro",
)
MODULE_REWRITE_CACHED_UNIT_PURE_SCOPE = (
    "module_rewrite_unit_cached_pure", 7, "compiler/module_registry.ouro",
)
_MODULE_PURE_SCOPE_DECL = (
    "ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity);\n"
)
MODULE_PURE_SCOPE_PREFIXES = (
    ("module_maps_for", 9, 2, "compiler/module_registry.ouro",
     "ouro_wrap_module_maps_for_scope"),
    ("module_rewrite_decls_with_opens_pure", 10, 3, "compiler/module_names.ouro",
     "ouro_wrap_module_rewrite_decls_scope"),
    ("module_rewrite_decl_pure", 10, 3, "compiler/module_names.ouro",
     "ouro_wrap_module_rewrite_decls_scope"),
    ("module_scope_maps", 4, 2, "compiler/module_registry.ouro",
     "ouro_wrap_module_scope_maps_scope"),
    ("module_bare_ctors", 5, 3, "compiler/module_registry.ouro",
     "ouro_wrap_module_bare_ctors_scope"),
    ("module_invalid_maps", 3, 1, "compiler/module_names_base.ouro",
     "ouro_wrap_module_invalid_maps_scope"),
    ("module_maps_for_cached_pure", 9, 2, "compiler/module_registry.ouro",
     "ouro_wrap_module_maps_for_scope"),
)
MODULE_PURE_SCOPE_OWNERS = (
    MODULE_PURE_SCOPE_OWNER, "compiler/module_registry.ouro", "compiler/module_names.ouro",
    "compiler/module_names_base.ouro",
)
_MODULE_PURE_SCOPE_PREFIX_DECLS = {
    wrapper: f"ouro_v *{wrapper}(ouro_v *raw);\n"
    for _name, _arity, _prefix, _owner, wrapper in MODULE_PURE_SCOPE_PREFIXES
}

MODULE_LOOKUP_OWNER = "compiler/module_names_base.ouro"
MODULE_LOOKUP_SOURCE_SHAPES = (
    (MODULE_LOOKUP_OWNER, "def", "module_lookup", """
def module_lookup : Nat -> List (Pair Nat Nat) -> Maybe Nat := lookup Nat Nat eqNat;
"""),
    ("std/listx.ouro", "def", "lookup", """
def lookup (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) : List (Pair A B) -> Maybe B :=
    fix lookup (xs : List (Pair A B)) : Maybe B :=
      match xs with
      | Nil => Nothing B
      | Cons p xs2 => match p with
        | MkPair a b => match eq a k with
          | True => Just B b
          | False => lookup xs2
          end
        end
      end;
"""),
    ("compiler/base.ouro", "def", "eqNat", """
def eqNat : Nat -> Nat -> Bool :=
  fix eqNat (n : Nat) (m : Nat) : Bool :=
    match n with
    | Z => match m with | Z => True | S _ => False end
    | S n' => match m with | Z => False | S m' => eqNat n' m' end
    end;
"""),
    ("std/types.ouro", "inductive", "Nat", "inductive Nat : Type := | Z : Nat | S : Nat -> Nat;"),
    ("std/types.ouro", "inductive", "Bool", "inductive Bool : Type := | True : Bool | False : Bool;"),
    ("std/types.ouro", "inductive", "List", """
inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
"""),
    ("std/types.ouro", "inductive", "Pair", """
inductive Pair (A : Type) (B : Type) : Type := | MkPair : A -> B -> Pair A B;
"""),
    ("std/types.ouro", "inductive", "Maybe", """
inductive Maybe (A : Type) : Type := | Nothing : Maybe A | Just : A -> Maybe A;
"""),
    *(('std/types.ouro', 'representation', name, f'representation {name} := "ouro.{tag}";')
      for name, tag in (('Nat', 'nat'), ('Bool', 'bool'), ('List', 'list'),
                        ('Pair', 'pair'), ('Maybe', 'maybe'))),
)
MODULE_LOOKUP_SOURCE_PATHS = tuple(dict.fromkeys(row[0] for row in MODULE_LOOKUP_SOURCE_SHAPES))
_MODULE_LOOKUP_DECL = "ouro_v *ouro_wrap_module_lookup(ouro_v *raw);\n"

LOWER_LOCAL_LOOKUP_OWNER = "compiler/lower_env.ouro"
# The shared pair wrapper returns Surface payloads without reading or retaining them.
LOWER_LOCAL_LOOKUP_SOURCE_SHAPES = (
    (LOWER_LOCAL_LOOKUP_OWNER, "def", "lookup_local", """
def lookup_local (nameId : Nat) : List (Pair Nat Surface) -> Maybe Surface :=
    fix go (xs : List (Pair Nat Surface)) : Maybe Surface :=
      match xs with
      | Nil => Nothing Surface
      | Cons p xs' =>
          match p with
          | MkPair n ty =>
              match eqNat n nameId with
              | True => Just Surface ty
              | False => go xs'
              end
          end
      end;
"""),
    ("compiler/core.ouro", "inductive", "Surface", """
inductive Surface : Type :=
  | SVar : Nat -> Surface
  | SSort : Nat -> Surface
  | SPi : Nat -> Surface -> Surface -> Surface
  | SLam : Nat -> Surface -> Surface -> Surface
  | SApp : Surface -> Surface -> Surface
  | SLet : Nat -> Surface -> Surface -> Surface -> Surface
  | SConst : Nat -> Surface
  | SInd : Nat -> Surface
  | SConstruct : Nat -> Nat -> Nat -> Surface
  | SCase : CaseInfo -> Surface -> Surface -> List Surface -> Surface
  | SFix : Nat -> Nat -> Nat -> Surface -> Surface -> Surface
  | SHole : Nat -> Surface
  | SEffectRow : Surface -> Surface
  | SPerform : Nat -> List Surface -> Surface
  | SStr : Nat -> Nat -> Surface;
"""),
    *MODULE_LOOKUP_SOURCE_SHAPES[2:],
)
LOWER_LOCAL_LOOKUP_SOURCE_PATHS = tuple(dict.fromkeys(
    row[0] for row in LOWER_LOCAL_LOOKUP_SOURCE_SHAPES))


PRELUDE_ARITHMETIC_OWNER = "std/prelude.ouro"
PRELUDE_ARITHMETIC_SOURCE_SHAPES = (
    ("std/types.ouro", "inductive", "Nat", """
inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
"""),
    ("std/types.ouro", "representation", "Nat", 'representation Nat := "ouro.nat";'),
    (PRELUDE_ARITHMETIC_OWNER, "def", "add", """
def add : Nat -> Nat -> Nat :=
  fix add (n : Nat) (m : Nat) : Nat :=
    match n with | Z => m | S n' => S (add n' m) end;
"""),
    (PRELUDE_ARITHMETIC_OWNER, "def", "mul", """
def mul : Nat -> Nat -> Nat :=
  fix mul (n : Nat) (m : Nat) : Nat :=
    match n with | Z => Z | S n' => add(m, mul n' m) end;
"""),
    (PRELUDE_ARITHMETIC_OWNER, "def", "sub", """
def sub : Nat -> Nat -> Nat :=
  fix sub (n : Nat) (m : Nat) : Nat :=
    match n with
    | Z => Z
    | S n' =>
      match m with
      | Z => n
      | S m' => sub n' m'
      end
    end;
"""),
)
PRELUDE_ARITHMETIC_SOURCE_PATHS = tuple(dict.fromkeys(
    row[0] for row in PRELUDE_ARITHMETIC_SOURCE_SHAPES))
NAT_COMPARE_OWNER = "std/data.ouro"
NAT_COMPARE_SOURCE_SHAPES = (
    *PRELUDE_ARITHMETIC_SOURCE_SHAPES[:2],
    ("std/types.ouro", "inductive", "Ordering", """
inductive Ordering : Type := | LT : Ordering | EQ : Ordering | GT : Ordering;
"""),
    (NAT_COMPARE_OWNER, "def", "compareNat", """
def compareNat : Nat -> Nat -> Ordering :=
  fix compareNat (n : Nat) (m : Nat) : Ordering :=
    match n, m with
    | Z, Z => EQ
    | Z, S _ => LT
    | S _, Z => GT
    | S n', S m' => compareNat n' m'
    end;
"""),
)
NAT_EQUALITY_OWNER = "compiler/base.ouro"
NAT_EQUALITY_SOURCE_SHAPES = (
    *PRELUDE_ARITHMETIC_SOURCE_SHAPES[:2],
    ("std/types.ouro", "inductive", "Bool",
     "inductive Bool : Type := | True : Bool | False : Bool;"),
    ("std/types.ouro", "representation", "Bool", 'representation Bool := "ouro.bool";'),
    (NAT_EQUALITY_OWNER, "def", "eqNat", """
def eqNat : Nat -> Nat -> Bool :=
  fix eqNat (n : Nat) (m : Nat) : Bool :=
    match n with
    | Z => match m with | Z => True | S _ => False end
    | S n' => match m with | Z => False | S m' => eqNat n' m' end
    end;
"""),
)
PRELUDE_ARITHMETIC_ROUTES = (
    ("add", PRELUDE_ARITHMETIC_OWNER),
    ("mul", PRELUDE_ARITHMETIC_OWNER),
    ("sub", PRELUDE_ARITHMETIC_OWNER),
    ("compareNat", NAT_COMPARE_OWNER),
    ("eqNat", NAT_EQUALITY_OWNER),
)
PRELUDE_LIST_LENGTH_ROUTE = ("length", PRELUDE_ARITHMETIC_OWNER, 1)
PRELUDE_LIST_LENGTH_SOURCE_SHAPES = (
    *PRELUDE_ARITHMETIC_SOURCE_SHAPES[:2],
    ("std/types.ouro", "inductive", "List", """
inductive List (A : Type) : Type :=
  | Nil : List A | Cons : A -> List A -> List A;
"""),
    ("std/types.ouro", "representation", "List", 'representation List := "ouro.list";'),
    (PRELUDE_ARITHMETIC_OWNER, "def", "length", """
def length (A : Type) : List A -> Nat :=
    fix length (xs : List A) : Nat :=
      match xs with
      | Nil => Z
      | Cons _ xs' => S (length xs')
      end;
"""),
)


PRELUDE_LIST_APPEND_ROUTE = ("append", PRELUDE_ARITHMETIC_OWNER, 2)
PRELUDE_LIST_APPEND_SOURCE_SHAPES = (
    *PRELUDE_LIST_LENGTH_SOURCE_SHAPES[:4],
    (PRELUDE_ARITHMETIC_OWNER, "def", "append", """
def append (A : Type) : List A -> List A -> List A :=
    fix append (xs : List A) : List A -> List A :=
      match xs with
      | Nil => fun (ys : List A) => ys
      | Cons x xs' => fun (ys : List A) => Cons A x (append xs' ys)
      end;
"""),
)


SOURCE_NAME_COMPARE_OWNER = "compiler/source_name_index.ouro"
SOURCE_NAME_COMPARE_SOURCE_SHAPES = (
    *PRELUDE_LIST_LENGTH_SOURCE_SHAPES[:4],
    *NAT_COMPARE_SOURCE_SHAPES[2:],
    (SOURCE_NAME_COMPARE_OWNER, "def", "source_name_compare", """
def source_name_compare : List Nat -> List Nat -> Ordering :=
  fix compare (left : List Nat) (right : List Nat) : Ordering :=
    match left with
    | Nil => match right with | Nil => EQ | Cons _ _ => LT end
    | Cons byte rest => match right with
      | Nil => GT
      | Cons other tail => match compareNat byte other with
        | EQ => compare rest tail
        | LT => LT
        | GT => GT
        end
      end
    end;
"""),
)
SOURCE_NAME_COMPARE_SOURCE_PATHS = tuple(dict.fromkeys(
    row[0] for row in SOURCE_NAME_COMPARE_SOURCE_SHAPES))


ELEM_OWNER = "std/data.ouro"
ELEM_ORB_OWNER = "std/prelude.ouro"
ELEM_VALUE_ARITY = 3
ELEM_SOURCE_SHAPES = (
    *PRELUDE_LIST_LENGTH_SOURCE_SHAPES[2:4],
    ("std/types.ouro", "inductive", "Bool", """
inductive Bool : Type := | True : Bool | False : Bool;
"""),
    ("std/types.ouro", "representation", "Bool", 'representation Bool := "ouro.bool";'),
    (ELEM_ORB_OWNER, "def", "orb", """
def orb (x : Bool) (y : Bool) : Bool :=
    match x with | True => True | False => y end;
"""),
    (ELEM_OWNER, "def", "elem", """
def elem (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> Bool :=
    fix elem (xs : List A) : Bool :=
      match xs with
      | Nil => False
      | Cons y ys => orb(eq x y, elem ys)
      end;
"""),
)
ELEM_SOURCE_PATHS = tuple(dict.fromkeys(row[0] for row in ELEM_SOURCE_SHAPES))


PE_FIXUP_STEP_OWNER = "compiler/native/pe_fixups.ouro"
PE_FIXUP_STEP_SOURCE_SHAPES = (
    ("std/types.ouro", "inductive", "Unit",
     "inductive Unit : Type := | MkUnit : Unit;"),
    ("std/types.ouro", "representation", "Unit", 'representation Unit := "ouro.unit";'),
    (PE_FIXUP_STEP_OWNER, "inductive", "PeFixupStep", """
inductive PeFixupStep : Type :=
  | PeFixupStepOf : PePatch -> Nat -> Nat -> List Nat -> PeFixupStep;
"""),
    (PE_FIXUP_STEP_OWNER, "def", "pe_run_fixup_step", """
def pe_run_fixup_step (work : Unit -> Either PeError PeFixupStep) : Either PeError PeFixupStep :=
    work MkUnit;
"""),
    (PE_FIXUP_STEP_OWNER, "def", "pe_plan_fixup_step", """
def pe_plan_fixup_step (lookup : PeSection -> Maybe (Pair PePlacedSection Nat))
    (index : PeSymbolIndex) (imports : List (Pair Nat Nat)) (fixup : PeFixup)
    (last_section : Nat) (last_end : Nat) (available : Bool) (source : List Nat) (_ : Unit)
    : Either PeError PeFixupStep :=
    let kind : PeSection := pe_fixup_section fixup in
    let offset : Nat := pe_fixup_offset fixup in
    let width : Nat := pe_fixup_width fixup in
    let code : Nat := pe_section_code kind in
    match pe_patch_bounds_with lookup kind offset width with
    | Left error => Left PeError PeFixupStep error
    | Right extent => match extent with | MkPair section _ =>
      match section with | PeSectionAt _ _ _ _ original =>
      let slot : List Nat := match andb(available, andb(eq_nat last_section code, leb_nat last_end offset)) with
        | True => drop Nat (sub offset last_end) source
        | False => drop Nat offset original end in
      match pe_bytes_equal(take Nat width slot, pe_zeros width) with
      | False => Left(PeError, PeFixupStep, PeNonzeroFixup offset)
      | True => match pe_resolve_fixup_indexed_with lookup index imports fixup extent with
    | Left err => Left PeError PeFixupStep err
    | Right patch => match patch with | PePatchAt _ patch_offset bytes _ =>
      match orb(ltb_nat last_section code, andb(eq_nat last_section code, leb_nat last_end patch_offset)) with
      | False => Left(PeError, PeFixupStep, PeUnorderedFixup patch_offset)
      | True => Right(PeError, PeFixupStep,
          PeFixupStepOf patch code (add(patch_offset, length Nat bytes)) (drop Nat width slot))
      end end
    end end end end end;
"""),
    (PE_FIXUP_STEP_OWNER, "def", "pe_plan_fixups_with", """
def pe_plan_fixups_with
    (run_step : (Unit -> Either PeError PeFixupStep) -> Either PeError PeFixupStep)
    (sections : List PePlacedSection) (symbols : List PeSymbol)
    (imports : List (Pair Nat Nat)) (fixups : List PeFixup) : Either PeError (List PePatch) :=
    match fixups with
    | Nil => Right(PeError, List PePatch, [] : List PePatch)
    | Cons _ _ =>
    let measured : List (Pair PePlacedSection Nat) := map PePlacedSection (Pair PePlacedSection Nat) pe_section_measure sections in
    let lookup : PeSection -> Maybe (Pair PePlacedSection Nat) := pe_cached_section_lookup measured in
    let index : PeSymbolIndex := pe_symbol_index_from_symbols symbols in
    (fix go (rest : List PeFixup) (last_section : Nat) (last_end : Nat)
        (available : Bool) (source : List Nat) : Either PeError (List PePatch) :=
      match rest with
      | Nil => Right(PeError, List PePatch, [] : List PePatch)
      | Cons fixup tail =>
        match run_step (pe_plan_fixup_step lookup index imports fixup last_section last_end available source) with
        | Left error => Left PeError (List PePatch) error
        | Right step => match step with | PeFixupStepOf patch code next_end next_source =>
          mapRight PeError (List PePatch) (List PePatch)
            (fun (patches : List PePatch) => Cons PePatch patch patches)
            (go tail code next_end True next_source)
          end
        end
      end) fixups 0 0 False ([] : List Nat)
    end;
"""),
    (PE_FIXUP_STEP_OWNER, "def", "pe_plan_fixups", """
def pe_plan_fixups (sections : List PePlacedSection) (symbols : List PeSymbol)
    (imports : List (Pair Nat Nat)) (fixups : List PeFixup) : Either PeError (List PePatch) :=
    pe_plan_fixups_with pe_run_fixup_step sections symbols imports fixups;
"""),
)


def prelude_arithmetic_source_paths(units):
    return (*PRELUDE_ARITHMETIC_SOURCE_PATHS,
            *((NAT_COMPARE_OWNER,) if NAT_COMPARE_OWNER in units or NAT_EQUALITY_OWNER in units else ()),
            *((NAT_EQUALITY_OWNER,) if NAT_EQUALITY_OWNER in units else ()))


class _SourceShapeTokens(NamedTuple):
    source: str
    values: list[str]
    starts: dict[tuple[bool, str], int | None]


def require_source_shapes(sources, shapes, label, *, token_cache=None):
    """Check shapes in order using token values from the same source snapshot."""
    token_cache = {} if token_cache is None else token_cache
    heads = {"def", "axiom", "inductive", "record", "effect", "intrinsic", "extern"}
    for owner, kind, name, expected in shapes:
        if owner not in sources:
            raise RuntimeError("missing " + label + " source " + owner)
        source = sources[owner]
        cached = token_cache.get(owner)
        if cached is None or cached.source != source:
            try:
                tokens, _comments = lex(source, "ouro")
            except ValueError as error:
                raise RuntimeError("unsupported " + label + " source " + owner) from error
            values = [token.value for token in tokens]
            starts = {}
            for index in range(len(values) - 1):
                head = values[index]
                is_representation = head == "representation"
                if is_representation or head in heads:
                    key = (is_representation, values[index + 1])
                    starts[key] = None if key in starts else index
            cached = _SourceShapeTokens(source, values, starts)
            token_cache[owner] = cached
        values, starts = cached.values, cached.starts
        start = starts.get((kind == "representation", name))
        if start is None:
            raise RuntimeError("missing or duplicate " + label + " source declaration " + name)
        if values[start] != kind or (start > 0 and values[start - 1] not in {";", "end"}):
            raise RuntimeError("private or unsupported " + label + " source declaration " + name)
        try:
            stop = values.index(";", start) + 1
        except ValueError as error:
            raise RuntimeError("unterminated " + label + " source declaration " + name) from error
        expected_tokens, _comments = lex(expected, "ouro")
        if values[start:stop] != [token.value for token in expected_tokens]:
            raise RuntimeError(label + " source shape changed: " + owner + ":" + name)
    return token_cache


def source_name_compare_source_contract(sources, *, token_cache=None):
    token_cache = require_source_shapes(sources, SOURCE_NAME_COMPARE_SOURCE_SHAPES, "source name compare scope",
                                        token_cache=token_cache)
    values = token_cache[NAT_COMPARE_OWNER].values
    expected, _comments = lex('import "prelude.ouro";', "ouro")
    prefix = [token.value for token in expected]
    if values[:len(prefix)] != prefix or values.count("import") != 1:
        raise RuntimeError("source name compare scope Nat comparison imports changed")
    values = token_cache[SOURCE_NAME_COMPARE_OWNER].values
    expected, _comments = lex('import "source_text.ouro";', "ouro")
    prefix = [token.value for token in expected]
    if values[:len(prefix)] != prefix or values.count("import") != 1:
        raise RuntimeError("source name compare scope source imports changed")
    values = token_cache["std/types.ouro"].values
    if any(values[index:index + 2] == ["representation", "Ordering"]
           for index in range(len(values) - 1)):
        raise RuntimeError("source name compare scope Ordering representation changed")


def elem_source_contract(sources, *, token_cache=None):
    token_cache = require_source_shapes(sources, ELEM_SOURCE_SHAPES, "elem scope", token_cache=token_cache)
    for owner, expected in ((ELEM_OWNER, 'import "prelude.ouro";'),
                            (ELEM_ORB_OWNER, 'import "types.ouro";')):
        values = token_cache[owner].values
        prefix, _comments = lex(expected, "ouro")
        expected_values = [token.value for token in prefix]
        if values[:len(expected_values)] != expected_values or values.count("import") != 1:
            raise RuntimeError("elem scope imports changed: " + owner)


def _static_symbol_starts(text: str) -> dict[str, list[int]]:
    # Literal headers can start inside identifiers. Keep nested static starts.
    # Keep duplicate suffixes in the candidate family without parsing their values.
    starts: dict[str, list[int]] = {}
    for prefix in re.finditer(
            r"static(?=\s+ouro_v\s*\*\s*(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))", text):
        base = _D_SUFFIX.sub("", prefix.group("symbol"))
        starts.setdefault(base, []).append(prefix.start())
    return starts


def _static_definition_family_counts(text: str) -> Counter[str]:
    return Counter(_base_ver(match[1])[0] for match in _SCOPED_STATIC_DEFINITION.finditer(text))


class StaticSymbolIndex:
    """Keep symbol positions, function counts, and export tables for one C text."""

    def __init__(self, text: str, *, export_index: ScopedExportIndex | None = None,
                 shape_tokens: dict[str, _SourceShapeTokens] | None = None) -> None:
        self._text = text
        self._export_index = export_index
        self.shape_tokens = {} if shape_tokens is None else shape_tokens

    @classmethod
    def for_text(cls, text: str, index: StaticSymbolIndex | None) -> StaticSymbolIndex:
        if index is None:
            return cls(text)
        if index.text is text:
            return index
        return cls(text, export_index=index.exports, shape_tokens=index.shape_tokens)

    @property
    def text(self) -> str:
        return self._text

    @cached_property
    def starts(self) -> dict[str, list[int]]:
        return _static_symbol_starts(self._text)

    @cached_property
    def definition_counts(self) -> Counter[str]:
        return _static_definition_family_counts(self._text)

    @cached_property
    def exports(self) -> ScopedExportIndex:
        return ScopedExportIndex() if self._export_index is None else self._export_index


def _static_symbol_matches(text: str, pattern: str, starts: dict[str, list[int]],
                           symbol: str | None = None) -> list[re.Match[str]]:
    if symbol is None:
        return list(re.finditer(pattern, text))
    expression = re.compile(pattern)
    base = _D_SUFFIX.sub("", symbol)
    matches = []
    end = 0
    for start in starts.get(base, ()):
        # Match order and overlap must agree with finditer.
        if start < end:
            continue
        match = expression.match(text, start)
        if match is not None:
            matches.append(match)
            end = match.end()
    return matches


def hook_elem_scope(text, units, canonical_units, entry, sources, module="", *, installed=False,
                    static_index: StaticSymbolIndex | None = None):
    name, wrapper = "elem_scope", "ouro_wrap_elem_scope"
    if ELEM_OWNER not in units:
        if wrapper in text:
            raise RuntimeError("elem scope source owner is absent")
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    elem_source_contract(sources, token_cache=static_index.shape_tokens)
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources,
        ((name, "elem", (ELEM_OWNER,)), ("elem_scope_orb", "orb", (ELEM_ORB_OWNER,))), module,
        export_index=static_index.exports)
    if set(getters) != {name, "elem_scope_orb"}:
        raise RuntimeError("missing elem scope binding")
    getter, orb = getters[name], getters["elem_scope_orb"]
    gid = getter[len("ouro_g"):]
    cache = "ouro_c" + gid
    definition_counts = static_index.definition_counts
    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate elem scope " + label)
        return matches[0]

    capture = "ouro_env *env=ouro_cons(arg,env0);(void)env;return "
    bodies = (
        (f"ouro_f{gid}_", f"ouro_clos(ouro_f0_{gid}_,env)"),
        (f"ouro_f0_{gid}_", f"ouro_fix(ouro_f0_0_{gid}_,env)"),
        (f"ouro_f0_0_{gid}_", "ouro_case(ouro_get(env,0),2,(ouro_v *[]){"
         f"ouro_thunk(ouro_t1_0_0_0_{gid}_,env),ouro_clos(ouro_f2_0_0_0_{gid}_,env)}})"),
        (f"ouro_f2_0_0_0_{gid}_", f"ouro_clos(ouro_f0_2_0_0_0_{gid}_,env)"),
        (f"ouro_f0_2_0_0_0_{gid}_", f"ouro_app(ouro_app({orb}(),"
         "ouro_app(ouro_app(ouro_get(env,5),ouro_get(env,4)),ouro_get(env,1))),"
         "ouro_app(ouro_get(env,3),ouro_get(env,0)))"),
    )
    thunk = f"ouro_t1_0_0_0_{gid}_"
    family = {thunk, *(function for function, _body in bodies)}
    pattern = re.compile(rf"ouro_[ft](?:[0-9]+_)*{re.escape(gid)}_")
    present = {name for name in definition_counts if pattern.fullmatch(name)}
    if present != family or any(definition_counts[name] != 1 for name in family):
        raise RuntimeError("missing, unexpected or duplicate elem scope helper family")
    if definition_counts[getter] != 1:
        raise RuntimeError("missing or duplicate elem scope function family")
    for symbol in (thunk, *(function for function, _body in bodies)):
        if len(re.findall(r"\b" + re.escape(symbol) + r"\b", text)) != 2:
            raise RuntimeError("unexpected elem scope helper reference")
    unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", "cache declaration", symbol=cache)
    unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
    for function, body in bodies:
        header = f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
        unique(r"(?m)^" + re.escape(header + capture + body + ";}") + r"\r?\n", function + " body", symbol=function)
    unique(r"(?m)^" + re.escape(f"static ouro_v *{thunk}(ouro_env *env,ouro_v *arg){{"
           "(void)arg;(void)env;return ouro_ctor(1,0,0);}") + r"\r?\n", "Nil body", symbol=thunk)
    raw = f"ouro_clos(ouro_f{gid}_,env)"
    value = f"{wrapper}({raw})" if installed else raw
    header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
              f"if({cache}==0){{ouro_static_begin();{cache}=")
    tail = f";ouro_static_end();}}return {cache};}}"
    match = unique(r"\b" + re.escape(header + value + tail), "getter", symbol=getter)
    declaration = f"ouro_v *{wrapper}(ouro_v *raw);\n"
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    if installed:
        if text.count(declaration) != 1 or text.count(wrapper) != 2:
            raise RuntimeError("missing, duplicate or unexpected elem scope wrapper")
        return text
    if wrapper in text:
        raise RuntimeError("elem scope source is already transformed")
    return replace_spans(text, [(match.start(), match.end(), header + f"{wrapper}({raw})" + tail),
                                (include.end(), include.end(), declaration)])


def hook_source_name_compare_scope(text, units, canonical_units, entry, sources, module="", *, installed=False,
                                   static_index: StaticSymbolIndex | None = None):
    name, wrapper = "source_name_compare_scope", "ouro_wrap_source_name_compare_scope"
    if SOURCE_NAME_COMPARE_OWNER not in units:
        if wrapper in text:
            raise RuntimeError("source name compare scope source owner is absent")
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    source_name_compare_source_contract(sources, token_cache=static_index.shape_tokens)
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources,
        ((name, "source_name_compare", (SOURCE_NAME_COMPARE_OWNER,)),), module, export_index=static_index.exports)
    if set(getters) != {name}:
        raise RuntimeError("missing source name compare scope binding")
    getter = getters[name]
    gid, cache = getter[len("ouro_g"):], "ouro_c" + getter[len("ouro_g"):]
    definition_counts = static_index.definition_counts
    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate source name compare scope " + label)
        return matches[0]

    for symbol in (getter, "ouro_f" + gid + "_", "ouro_f0_" + gid + "_"):
        if definition_counts[symbol] != 1:
            raise RuntimeError("missing or duplicate source name compare scope function family")
    unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", "cache declaration", symbol=cache)
    unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
    capture = "ouro_env *env=ouro_cons(arg,env0);(void)env;return "
    for step in range(2):
        suffix = "0_" * step + gid + "_"
        function = "ouro_f" + suffix
        header = f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
        unique(r"\b" + re.escape(header + capture), f"curry capture {step + 1}", symbol=function)
        partial = re.escape(header + capture) + rf"ouro_(?:clos|fix)\(ouro_f0_{suffix},env\);\}}"
        if step == 0:
            unique(partial, "curry step 1", symbol=function)
        elif re.search(partial, text) is not None:
            raise RuntimeError("extra source name compare scope curry parameter")
        body = unique(r"(?m)^" + re.escape(header + capture) + r"[^\n]*\}\r?\n", f"curry body {step + 1}", symbol=function)
        try:
            tokens, _comments = lex(body.group(), "c")
            values = [token.value for token in tokens]
            opening = values.index("{")
        except ValueError as error:
            raise RuntimeError("malformed source name compare scope curry body") from error
        if pairs(values).get(opening) != len(values) - 1:
            raise RuntimeError("noncanonical source name compare scope curry body")
    raw = f"ouro_fix(ouro_f{gid}_,env)"
    value = f"{wrapper}({raw})" if installed else raw
    header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
              f"if({cache}==0){{ouro_static_begin();{cache}=")
    tail = f";ouro_static_end();}}return {cache};}}"
    match = unique(r"\b" + re.escape(header + value + tail), "getter", symbol=getter)
    declaration = f"ouro_v *{wrapper}(ouro_v *raw);\n"
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    if installed:
        if text.count(declaration) != 1 or text.count(wrapper) != 2:
            raise RuntimeError("missing, duplicate or unexpected source name compare scope wrapper")
        return text
    if wrapper in text:
        raise RuntimeError("source name compare scope source is already transformed")
    return replace_spans(text, [(match.start(), match.end(), header + f"{wrapper}({raw})" + tail),
                                (include.end(), include.end(), declaration)])


def hook_pe_fixup_step(text, units, canonical_units, entry, sources, *, installed=False,
                      static_index: StaticSymbolIndex | None = None):
    name = "pe_run_fixup_step"
    wrapper = "ouro_wrap_pe_run_fixup_step"
    if PE_FIXUP_STEP_OWNER not in units:
        if wrapper in text or re.search(r'"(?:_ouro_m_[0-9]+_)?pe_run_fixup_step"', text):
            raise RuntimeError("PE fixup step source owner is absent")
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    require_source_shapes(sources, PE_FIXUP_STEP_SOURCE_SHAPES, "PE fixup step", token_cache=static_index.shape_tokens)
    routes = ((name, name, (PE_FIXUP_STEP_OWNER,)),)
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources, routes,
                                         export_index=static_index.exports)
    if set(getters) != {name}:
        raise RuntimeError("missing PE fixup step binding")
    getter = getters[name]
    gid = getter[len("ouro_g"):]
    cache = "ouro_c" + gid
    function = "ouro_f" + gid + "_"
    definitions = _SCOPED_STATIC_DEFINITION.findall(text)

    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate PE fixup step " + label)
        return matches[0]

    for symbol in (getter, function):
        if sum(_base_ver(value)[0] == symbol for value in definitions) != 1:
            raise RuntimeError("missing or duplicate PE fixup step function family")
    if any(re.fullmatch(r"ouro_f(?:0_)+" + re.escape(gid) + r"_(?:_d[0-9]+)?", value)
           for value in definitions):
        raise RuntimeError("extra PE fixup step curry parameter")
    unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", "cache declaration", symbol=cache)
    unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
    body = (f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
            "ouro_env *env=ouro_cons(arg,env0);(void)env;"
            "return ouro_app(ouro_get(env,0),ouro_ctor(0,0,0));}")
    unique(r"\b" + re.escape(body), "runner body", symbol=function)
    raw = f"ouro_clos({function},env)"
    value = f"{wrapper}({raw})" if installed else raw
    header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
              f"if({cache}==0){{ouro_static_begin();{cache}=")
    tail = f";ouro_static_end();}}return {cache};}}"
    match = unique(r"\b" + re.escape(header + value + tail), "getter", symbol=getter)
    declaration = f"ouro_v *{wrapper}(ouro_v *raw);\n"
    position = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include").end()
    getter_start, getter_end = match.span()
    if position > getter_start:
        raise RuntimeError("PE fixup step runtime include must precede getter")
    if installed:
        if text.count(declaration) != 1 or text.count(wrapper) != 2:
            raise RuntimeError("missing, duplicate or unexpected PE fixup step wrapper")
        if text.find(declaration, 0, getter_start) < 0:
            raise RuntimeError("PE fixup step wrapper declaration must precede getter")
        return text
    if wrapper in text:
        raise RuntimeError("PE fixup step source is already transformed")
    replacement = header + f"{wrapper}({raw})" + tail
    return replace_spans(text, [
        (getter_start, getter_end, replacement),
        (position, position, declaration),
    ])


def prelude_list_length_source_contract(sources, *, token_cache=None):
    require_source_shapes(sources, PRELUDE_LIST_LENGTH_SOURCE_SHAPES, "prelude list length", token_cache=token_cache)


def prelude_arithmetic_source_contract(sources, *, token_cache=None):
    token_cache = require_source_shapes(sources, PRELUDE_ARITHMETIC_SOURCE_SHAPES, "prelude arithmetic",
                                        token_cache=token_cache)
    prelude_list_length_source_contract(sources, token_cache=token_cache)
    require_source_shapes(sources, PRELUDE_LIST_APPEND_SOURCE_SHAPES, "prelude list append", token_cache=token_cache)
    values = token_cache[PRELUDE_ARITHMETIC_OWNER].values
    expected, _comments = lex('import "types.ouro";', "ouro")
    prefix = [token.value for token in expected]
    if values[:len(prefix)] != prefix or values.count("import") != 1:
        raise RuntimeError("prelude arithmetic source imports changed")
    if NAT_COMPARE_OWNER in sources:
        require_source_shapes(sources, NAT_COMPARE_SOURCE_SHAPES, "Nat comparison", token_cache=token_cache)
        values = token_cache[NAT_COMPARE_OWNER].values
        expected, _comments = lex('import "prelude.ouro";', "ouro")
        prefix = [token.value for token in expected]
        if values[:len(prefix)] != prefix or values.count("import") != 1:
            raise RuntimeError("Nat comparison source imports changed")
        values = token_cache["std/types.ouro"].values
        # The existing C comparison returns unrepresented LT, EQ and GT tags in this order.
        if any(values[index:index + 2] == ["representation", "Ordering"]
               for index in range(len(values) - 1)):
            raise RuntimeError("Nat comparison Ordering representation changed")
    if NAT_EQUALITY_OWNER in sources:
        if NAT_COMPARE_OWNER not in sources:
            raise RuntimeError("Nat equality comparison source is missing")
        require_source_shapes(sources, NAT_EQUALITY_SOURCE_SHAPES, "Nat equality", token_cache=token_cache)
        values = token_cache[NAT_EQUALITY_OWNER].values
        expected, _comments = lex('import "../std/data.ouro";', "ouro")
        prefix = [token.value for token in expected]
        if values[:len(prefix)] != prefix or values.count("import") != 1:
            raise RuntimeError("Nat equality source imports changed")


def hook_prelude_arithmetic(text, units, canonical_units, entry, sources,
                           module="", *, installed=False, static_index: StaticSymbolIndex | None = None):
    fast_pattern = r'\bouro_fast\s*\(\s*"(add|mul|sub|compareNat|eqNat|length|append)"\s*\)'
    value_routes = (*PRELUDE_ARITHMETIC_ROUTES, PRELUDE_LIST_LENGTH_ROUTE[:2],
                    PRELUDE_LIST_APPEND_ROUTE[:2])
    selected = tuple((name, owner) for name, owner in value_routes if owner in units)
    names = tuple(name for name, _owner in selected)
    if not selected:
        if re.search(fast_pattern, text):
            raise RuntimeError("canonical Nat/List fast value source owner is absent")
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    prelude_arithmetic_source_contract(sources, token_cache=static_index.shape_tokens)
    routes = tuple((name, name, (owner,)) for name, owner in selected)
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources, routes, module,
                                         export_index=static_index.exports)
    getter_symbols = set(getters.values())
    if set(getters) != set(names) or len(getter_symbols) != len(names):
        raise RuntimeError("missing or aliased canonical Nat/List fast value dependency")
    definition_counts: Counter[str] = Counter()
    helpers_by_getter: dict[str, list[str]] = {getter[len("ouro_g"):]: [] for getter in getters.values()}
    for declaration in _SCOPED_STATIC_DEFINITION.finditer(text):
        symbol = declaration[1]
        base = _base_ver(symbol)[0]
        helper = _PRELUDE_HELPER_DEFINITION.fullmatch(symbol)
        if helper is not None and helper[1] in helpers_by_getter:
            helpers_by_getter[helper[1]].append(symbol)
        elif base not in getter_symbols:
            continue
        definition_counts[base] += 1

    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate canonical Nat/List fast value " + label)
        return matches[0]

    replacements = []
    removed_families = []
    for name in names:
        getter = getters[name]
        gid = getter[len("ouro_g"):]
        cache = "ouro_c" + gid
        if definition_counts[getter] != 1:
            raise RuntimeError("missing or duplicate canonical Nat/List fast value getter family")
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{re.escape(cache)}(?:_d[0-9]+)?\b",
               name + " cache declaration", symbol=cache)
        unique(re.escape(f"static ouro_v *{cache};"), name + " cache", symbol=cache)
        fast = (f'static ouro_v *{getter}(void){{if({cache}==0)'
                f'{cache}=ouro_fast("{name}");return {cache};}}')
        family = rf"ouro_[ft](?:[0-9]+_)*{re.escape(gid)}_(?:_d[0-9]+)?"
        removed_families.append(family)
        helpers = helpers_by_getter[gid]
        already_fast = text.count(fast) == 1
        if already_fast and not helpers:
            continue
        if installed:
            raise RuntimeError("noncanonical installed canonical Nat/List fast value getter " + name)
        header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
                  f"if({cache}==0){{ouro_static_begin();{cache}=")
        tail = f";ouro_static_end();}}return {cache};}}"
        if not already_fast:
            initializer = (re.escape(f"ouro_fix(ouro_f{gid}_,env)") if name == "append" else
                           rf"ouro_(?:clos|fix)\(ouro_f{re.escape(gid)}_,env\)")
            raw = unique(re.escape(header) + initializer
                         + re.escape(tail), name + " getter", symbol=getter)
            replacements.append((raw.start(), raw.end(), fast))
        if name == "append":
            # append matches xs before capturing ys in either constructor arm.
            expected = {
                f"ouro_f1_0_{gid}_": "ouro_get(env,0)",
                f"ouro_f0_0_2_0_{gid}_": (
                    "ouro_ctor(1,2,(ouro_v *[]){ouro_get(env,2),"
                    "ouro_app(ouro_app(ouro_get(env,4),ouro_get(env,1)),ouro_get(env,0))})"),
                f"ouro_f0_2_0_{gid}_": f"ouro_clos(ouro_f0_0_2_0_{gid}_,env)",
                f"ouro_f2_0_{gid}_": f"ouro_clos(ouro_f0_2_0_{gid}_,env)",
                f"ouro_f{gid}_": (
                    "ouro_case(ouro_get(env,0),2,(ouro_v *[]){"
                    f"ouro_clos(ouro_f1_0_{gid}_,env),ouro_clos(ouro_f2_0_{gid}_,env)}})"),
            }
            if len(helpers) != len(expected) or set(helpers) != set(expected):
                raise RuntimeError("missing or duplicate canonical Nat/List fast value append helper family")
            for function, result in expected.items():
                body = (f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
                        f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}")
                unique(r"(?m)^" + re.escape(body) + r"\r?\n", "append helper body", symbol=function)
        else:
            arity = PRELUDE_LIST_LENGTH_ROUTE[2] if name == PRELUDE_LIST_LENGTH_ROUTE[0] else 2
            for step in range(arity):
                suffix = "0_" * step + gid + "_"
                function = "ouro_f" + suffix
                if definition_counts[function] != 1:
                    raise RuntimeError("missing or duplicate canonical Nat/List fast value curry family")
                capture = (f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
                           "ouro_env *env=ouro_cons(arg,env0);(void)env;return ")
                unique(re.escape(capture), name + " curry capture", symbol=function)
                partial = re.escape(capture) + rf"ouro_(?:clos|fix)\(ouro_f0_{re.escape(suffix)},env\);\}}"
                if step + 1 < arity:
                    unique(partial, name + " curry step", symbol=function)
                elif re.search(re.escape(capture) +
                               rf"ouro_(?:clos|fix)\s*\(\s*ouro_f0_{re.escape(suffix)}(?:_d[0-9]+)?\s*,\s*env\s*\)\s*;",
                               text) is not None:
                    raise RuntimeError("extra canonical Nat/List fast value curry parameter")
        for helper in helpers:
            body = unique(rf"(?m)^static ouro_v \*{re.escape(helper)}\([^;\n]*\)\{{[^\n]*\}}\r?\n",
                          name + " helper body", symbol=helper)
            try:
                tokens, _comments = lex(body.group(), "c")
                values = [token.value for token in tokens]
                opening = values.index("{")
            except ValueError as error:
                raise RuntimeError("malformed canonical Nat/List fast value helper body") from error
            if pairs(values).get(opening) != len(values) - 1:
                raise RuntimeError("noncanonical canonical Nat/List fast value helper body")
            replacements.append((body.start(), body.end(), ""))
    transformed = replace_spans(text, replacements)
    references = re.finditer(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
        + rf"|(?P<helper>\b(?:{'|'.join(removed_families)})\b)", transformed, re.DOTALL)
    if any(match.group("helper") is not None for match in references):
        raise RuntimeError("external reference to replaced canonical Nat/List fast value body")
    fast_calls = re.findall(fast_pattern, transformed)
    if len(fast_calls) != len(names) or any(fast_calls.count(name) != 1 for name in names):
        raise RuntimeError("unbound or duplicate canonical Nat/List fast getter")
    return transformed


def module_lookup_source_contract(sources, *, token_cache=None) -> None:
    require_source_shapes(sources, MODULE_LOOKUP_SOURCE_SHAPES, "module lookup", token_cache=token_cache)


def hook_module_lookup(text, units, canonical_units, entry, sources, module="", *, installed=False,
                       static_index: StaticSymbolIndex | None = None):
    if MODULE_LOOKUP_OWNER not in units:
        if "ouro_wrap_module_lookup" in text:
            raise RuntimeError("module lookup source owner is absent")
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    module_lookup_source_contract(sources, token_cache=static_index.shape_tokens)
    routes = tuple((name, name, (owner,)) for owner, kind, name, _expected
                   in MODULE_LOOKUP_SOURCE_SHAPES if kind == "def")
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources, routes, module,
                                         export_index=static_index.exports)
    if set(getters) != {"module_lookup", "lookup", "eqNat"} or len(set(getters.values())) != 3:
        raise RuntimeError("missing or aliased module lookup dependency")
    definition_counts = static_index.definition_counts
    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate module lookup " + label)
        return matches[0]

    def envelope(getter):
        gid = getter[len("ouro_g"):]
        cache = "ouro_c" + gid
        if definition_counts[getter] != 1:
            raise RuntimeError("missing or duplicate module lookup getter family")
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", "cache declaration", symbol=cache)
        unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
        header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
                  f"if({cache}==0){{ouro_static_begin();{cache}=")
        tail = f";ouro_static_end();}}return {cache};}}"
        return header, tail, cache, gid

    for name, arity in (("lookup", 3), ("eqNat", 2)):
        getter = getters[name]
        header, tail, cache, gid = envelope(getter)
        fast = (f'static ouro_v *{getter}(void){{if({cache}==0)'
                f'{cache}=ouro_fast("eqNat");return {cache};}}')
        if name == "eqNat" and text.count(fast) == 1:
            continue
        unique(re.escape(header) + rf"ouro_(?:clos|fix)\(ouro_f{gid}_,env\)" + re.escape(tail),
               name + " dependency getter", symbol=getter)
        for step in range(arity):
            suffix = "0_" * step + gid + "_"
            function = "ouro_f" + suffix
            if definition_counts[function] != 1:
                raise RuntimeError("missing or duplicate module lookup curry family")
            capture = (f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
                       "ouro_env *env=ouro_cons(arg,env0);(void)env;return ")
            unique(re.escape(capture), name + " curry capture", symbol=function)
            partial = re.escape(capture) + rf"ouro_(?:clos|fix)\(ouro_f0_{suffix},env\);\}}"
            if step + 1 < arity:
                unique(partial, name + " curry step", symbol=function)
            elif re.search(re.escape(capture) +
                           rf"ouro_(?:clos|fix)\s*\(\s*ouro_f0_{suffix}(?:_d[0-9]+)?\s*,\s*env\s*\)\s*;",
                           text) is not None:
                raise RuntimeError("extra module lookup curry parameter")
    raw = f"ouro_app({getters['lookup']}(),{getters['eqNat']}())"
    value = f"ouro_wrap_module_lookup({raw})" if installed else raw
    header, tail, _cache, _gid = envelope(getters["module_lookup"])
    match = unique(re.escape(header + value + tail), "alias getter", symbol=getters["module_lookup"])
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    if installed:
        local = LOWER_LOCAL_LOOKUP_OWNER in units and re.search(
            r"ouro_wrap_module_lookup\(ouro_(?:clos|fix)\(ouro_f[0-9]+_,env\)\)", text) is not None
        if local:
            hook_lower_local_lookup(text, units, canonical_units, entry, sources, module,
                                    installed=True, static_index=static_index)
        if text.count(_MODULE_LOOKUP_DECL) != 1 or text.count("ouro_wrap_module_lookup") != 2 + int(local):
            raise RuntimeError("missing, duplicate or unexpected module lookup wrapper")
        return text
    if "ouro_wrap_module_lookup" in text:
        raise RuntimeError("module lookup source is already transformed")
    return replace_spans(text, [(match.start(), match.end(), header + f"ouro_wrap_module_lookup({raw})" + tail),
        (include.end(), include.end(), _MODULE_LOOKUP_DECL)])


def lower_local_lookup_source_contract(sources, *, token_cache=None):
    token_cache = require_source_shapes(sources, LOWER_LOCAL_LOOKUP_SOURCE_SHAPES, "lower local lookup",
                                        token_cache=token_cache)
    for owner, expected in (
            (LOWER_LOCAL_LOOKUP_OWNER, 'import "../std/data.ouro", "ast.ouro", "core.ouro", "pipeline_abi.ouro";'),
            ("compiler/core.ouro", 'import "../std/data.ouro", "base.ouro";'),
            ("compiler/base.ouro", 'import "../std/data.ouro";')):
        values = token_cache[owner].values
        prefix, _comments = lex(expected, "ouro")
        expected_values = [token.value for token in prefix]
        if values[:len(expected_values)] != expected_values or values.count("import") != 1:
            raise RuntimeError("lower local lookup imports changed: " + owner)


def hook_lower_local_lookup(text, units, canonical_units, entry, sources, module="", *, installed=False,
                            static_index: StaticSymbolIndex | None = None):
    if LOWER_LOCAL_LOOKUP_OWNER not in units:
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)
    lower_local_lookup_source_contract(sources, token_cache=static_index.shape_tokens)
    routes = (("lookup_local", "lookup_local", (LOWER_LOCAL_LOOKUP_OWNER,)),
              ("eqNat", "eqNat", ("compiler/base.ouro",)))
    getters = scoped_host_export_getters(text, units, canonical_units, entry, sources, routes, module,
                                         export_index=static_index.exports)
    if set(getters) != {"lookup_local", "eqNat"} or len(set(getters.values())) != 2:
        raise RuntimeError("missing or aliased lower local lookup dependency")
    definition_counts = static_index.definition_counts
    static_starts = static_index.starts

    def unique(pattern, label, *, symbol=None):
        matches = _static_symbol_matches(text, pattern, static_starts, symbol)
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate lower local lookup " + label)
        return matches[0]

    def envelope(getter):
        gid = getter[len("ouro_g"):]
        cache = "ouro_c" + gid
        if definition_counts[getter] != 1:
            raise RuntimeError("missing or duplicate lower local lookup getter family")
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", "cache declaration", symbol=cache)
        unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
        header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
                  f"if({cache}==0){{ouro_static_begin();{cache}=")
        tail = f";ouro_static_end();}}return {cache};}}"
        return header, tail, cache, gid

    for name in ("lookup_local", "eqNat"):
        getter = getters[name]
        header, tail, cache, gid = envelope(getter)
        fast = (f'static ouro_v *{getter}(void){{if({cache}==0)'
                f'{cache}=ouro_fast("eqNat");return {cache};}}')
        if name == "eqNat" and text.count(fast) == 1:
            continue
        raw_pattern = rf"ouro_(?:clos|fix)\(ouro_f{gid}_,env\)"
        value = rf"ouro_wrap_module_lookup\({raw_pattern}\)" if installed and name == "lookup_local" else raw_pattern
        unique(re.escape(header) + value + re.escape(tail), name + " getter", symbol=getter)
        for step in range(2):
            suffix = "0_" * step + gid + "_"
            function = "ouro_f" + suffix
            if definition_counts[function] != 1:
                raise RuntimeError("missing or duplicate lower local lookup curry family")
            capture = (f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
                       "ouro_env *env=ouro_cons(arg,env0);(void)env;return ")
            unique(re.escape(capture), name + " curry capture", symbol=function)
            partial = re.escape(capture) + rf"ouro_(?:clos|fix)\(ouro_f0_{suffix},env\);\}}"
            if step == 0:
                unique(partial, name + " curry step", symbol=function)
            elif re.search(re.escape(capture) +
                           rf"ouro_(?:clos|fix)\s*\(\s*ouro_f0_{suffix}(?:_d[0-9]+)?\s*,\s*env\s*\)\s*;",
                           text) is not None:
                raise RuntimeError("extra lower local lookup curry parameter")
    # Install module_lookup first. Both getters share one runtime declaration.
    other = 0
    if MODULE_LOOKUP_OWNER in units:
        module_lookup_source_contract(sources, token_cache=static_index.shape_tokens)
        module_routes = tuple((name, name, (owner,)) for owner, kind, name, _expected
                              in MODULE_LOOKUP_SOURCE_SHAPES if kind == "def")
        module_getters = scoped_host_export_getters(
            text, units, canonical_units, entry, sources, module_routes, module, export_index=static_index.exports)
        if set(module_getters) != {"module_lookup", "lookup", "eqNat"}:
            raise RuntimeError("missing lower local lookup module companion")
        header, tail, _cache, _gid = envelope(module_getters["module_lookup"])
        raw = f"ouro_app({module_getters['lookup']}(),{module_getters['eqNat']}())"
        unique(re.escape(header + f"ouro_wrap_module_lookup({raw})" + tail), "module companion getter",
               symbol=module_getters["module_lookup"])
        other = 1
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    expected = 1 + other + int(installed) if other or installed else 0
    if (text.count("ouro_wrap_module_lookup") != expected
            or text.count(_MODULE_LOOKUP_DECL) != int(bool(other or installed))):
        raise RuntimeError("missing, duplicate or unexpected lower local lookup wrapper")
    if installed:
        return text
    header, tail, _cache, gid = envelope(getters["lookup_local"])
    match = unique(re.escape(header) + rf"(?P<raw>ouro_(?:clos|fix)\(ouro_f{gid}_,env\))"
                   + re.escape(tail), "raw getter", symbol=getters["lookup_local"])
    replacement = header + f"ouro_wrap_module_lookup({match.group('raw')})" + tail
    replacements = [(match.start(), match.end(), replacement)]
    if not other:
        replacements.append((include.end(), include.end(), _MODULE_LOOKUP_DECL))
    return replace_spans(text, replacements)


def hook_module_pure_scopes(
    text: str, units: list[str] | tuple[str, ...], module: str = "", *, installed: bool = False,
    static_index: StaticSymbolIndex | None = None,
) -> str:
    """Install or verify the closed source-owned pure lifetime seams."""
    sources = {str(unit).replace("\\", "/") for unit in units}
    if not sources.intersection(MODULE_PURE_SCOPE_OWNERS):
        return text
    routes = [(name, arity, "ouro_wrap_module_pure_scope")
              for name, arity in MODULE_PURE_SCOPE_ARITIES
              if MODULE_PURE_SCOPE_OWNER in sources]
    if MODULE_REWRITE_UNIT_PURE_SCOPE != (
            "module_rewrite_unit_pure", 7, "compiler/module_registry.ouro"):
        raise RuntimeError("invalid module rewrite unit pure scope contract")
    name, arity, owner = MODULE_REWRITE_UNIT_PURE_SCOPE
    if owner in sources:
        routes.append((name, arity, "ouro_wrap_module_pure_scope"))
    if tuple(row[0] for row in MODULE_PURE_SCOPE_PREFIXES) != (
            "module_maps_for", "module_rewrite_decls_with_opens_pure", "module_rewrite_decl_pure",
            "module_scope_maps", "module_bare_ctors", "module_invalid_maps",
            "module_maps_for_cached_pure"):
        raise RuntimeError("missing, reordered or duplicate module pure scope prefix contract")
    for name, arity, prefix, owner, wrapper in MODULE_PURE_SCOPE_PREFIXES:
        if name in ("module_scope_maps", "module_bare_ctors"):
            scope_maps = name == "module_scope_maps"
            if (prefix != (2 if scope_maps else 3) or arity != prefix + 2
                    or owner != "compiler/module_registry.ouro"
                    or wrapper != ("ouro_wrap_module_scope_maps_scope" if scope_maps
                                   else "ouro_wrap_module_bare_ctors_scope")):
                raise RuntimeError("invalid module pure scope prefix contract")
        elif name == "module_invalid_maps":
            if (arity != 3 or prefix != 1 or owner != "compiler/module_names_base.ouro"
                    or wrapper != "ouro_wrap_module_invalid_maps_scope"):
                raise RuntimeError("invalid module pure scope prefix contract")
        else:
            maps = name in ("module_maps_for", "module_maps_for_cached_pure")
            if (name not in ("module_maps_for", "module_maps_for_cached_pure",
                             "module_rewrite_decls_with_opens_pure", "module_rewrite_decl_pure")
                    or prefix != (2 if maps else 3) or arity != prefix + 7
                    or owner != ("compiler/module_registry.ouro" if maps else "compiler/module_names.ouro")
                    or wrapper != ("ouro_wrap_module_maps_for_scope" if maps
                                   else "ouro_wrap_module_rewrite_decls_scope")):
                raise RuntimeError("invalid module pure scope prefix contract")
        if owner in sources:
            routes.append((name, arity, wrapper))
    if MODULE_REWRITE_CACHED_UNIT_PURE_SCOPE != (
            "module_rewrite_unit_cached_pure", 7, "compiler/module_registry.ouro"):
        raise RuntimeError("invalid module rewrite cached unit pure scope contract")
    name, arity, owner = MODULE_REWRITE_CACHED_UNIT_PURE_SCOPE
    if owner in sources:
        routes.append((name, arity, "ouro_wrap_module_pure_scope"))
    if len({name for name, _arity, _wrapper in routes}) != len(routes):
        raise RuntimeError("duplicate module pure scope route")
    if module and re.fullmatch(r"_[A-Za-z0-9_]+", module) is None:
        raise RuntimeError("invalid module pure scope export suffix")

    static_starts = StaticSymbolIndex.for_text(text, static_index).starts

    def unique(pattern: str, label: str, *, symbol: str | None = None,
               prefix: str | None = None) -> re.Match[str]:
        matches = (_static_symbol_matches(text, pattern, static_starts, symbol) if prefix is None
                   else _literal_prefix_matches(pattern, text, prefix))
        if len(matches) != 1:
            raise RuntimeError(f"missing, malformed or duplicate module pure scope {label}")
        return matches[0]

    def table(kind: str, result_type: str, item: str, zero: str) -> str:
        export_name = f"ouro_export_{kind}{module}"
        header = f"{result_type}{export_name}(int i){{switch(i){{"
        unique(rf"\b{re.escape(export_name)}\s*\(int\s+i\)\s*\{{",
               f"{kind} declaration", prefix=export_name)
        if text.count(header) != 1:
            raise RuntimeError(f"malformed module pure scope {kind} table")
        rows = rf"(?P<rows>(?:\s*case [0-9]+:\s*return {item};)*)\s*"
        tail = rf"(?:\}}\s*return {zero};\s*\}}|default:\s*return {zero};\s*\}}\s*\}})"
        return unique(re.escape(header) + rows + tail, f"{kind} table").group("rows")

    count_name = f"ouro_export_count{module}"
    unique(rf"\b{re.escape(count_name)}\s*\(void\)\s*\{{", "count declaration", prefix=count_name)
    count = unique(
        rf"int ouro_export_count{re.escape(module)}\(void\)\{{return ([0-9]+);\}}",
        "count table",
    ).group(1)
    names = re.findall(
        r'case ([0-9]+):\s*return "((?:[^"\\]|\\.)*)";',
        table("name", "const char *", r'"(?:[^"\\]|\\.)*"', '""'),
    )
    values = re.findall(
        r"case ([0-9]+):\s*return (ouro_g[0-9]+)\(\);",
        table("value", "ouro_v *", r"ouro_g[0-9]+\(\)", "0"),
    )
    if count != str(len(names)) or len(values) != len(names):
        raise RuntimeError("malformed module pure scope export inventory")
    for rows in (names, values):
        if any(len(index) > len(count) or (index.startswith("0") and index != "0")
               for index, _ in rows):
            raise RuntimeError("noncanonical module pure scope export index")
        indices = [int(index) for index, _ in rows]
        if sorted(indices) != list(range(len(rows))):
            raise RuntimeError("malformed module pure scope export inventory")
    value_map = dict(values)
    prototypes = {"ouro_wrap_module_pure_scope": _MODULE_PURE_SCOPE_DECL,
                  **_MODULE_PURE_SCOPE_PREFIX_DECLS}
    wrappers = {wrapper for _name, _arity, wrapper in routes}
    declaration = "".join(prototype for wrapper, prototype in prototypes.items() if wrapper in wrappers)
    if installed:
        for wrapper, prototype in prototypes.items():
            if text.count(prototype) != int(wrapper in wrappers):
                raise RuntimeError("missing, duplicate or unexpected module pure scope prototype")
    elif any(wrapper in text for wrapper in prototypes):
        raise RuntimeError("module pure scope source is already transformed")
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    replacements: list[tuple[int, int, str]] = []
    seen_getters: set[str] = set()
    for name, arity, wrapper in routes:
        indices = [index for index, label in names if label == name]
        if len(indices) != 1:
            raise RuntimeError(f"missing or duplicate module pure scope export {name}")
        getter = value_map[indices[0]]
        if getter in seen_getters:
            raise RuntimeError(f"aliased module pure scope getter {name}")
        seen_getters.add(getter)
        gid = getter[len("ouro_g"):]
        cache = f"ouro_c{gid}"
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}\b", f"{name} cache declaration", symbol=cache)
        unique(re.escape(f"static ouro_v *{cache};"), f"{name} cache", symbol=cache)
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{getter}\s*\([^;{{]*\)\s*\{{",
               f"{name} getter declaration", symbol=getter)
        raw_pattern = rf"(?P<raw>ouro_(?:clos|fix)\(ouro_f{gid}_,env\))"
        argument = f",{arity}" if wrapper == "ouro_wrap_module_pure_scope" else ""
        value_pattern = (rf"{re.escape(wrapper)}\({raw_pattern}{argument}\)"
                         if installed else raw_pattern)
        header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
                  f"if({cache}==0){{ouro_static_begin();{cache}=")
        tail = f";ouro_static_end();}}return {cache};}}"
        match = unique(re.escape(header) + value_pattern + re.escape(tail), f"{name} getter", symbol=getter)
        for step in range(arity):
            suffix = "0_" * step + f"{gid}_"
            raw_header = f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
            unique(rf"\bstatic\s+ouro_v\s*\*\s*ouro_f{suffix}\s*\([^;{{]*\)\s*\{{",
                   f"{name} curry declaration {step + 1}", symbol=f"ouro_f{suffix}")
            unique(re.escape(raw_header), f"{name} curry header {step + 1}", symbol=f"ouro_f{suffix}")
            partial = (re.escape(raw_header + "ouro_env *env=ouro_cons(arg,env0);(void)env;return ")
                       + rf"ouro_(?:clos|fix)\(ouro_f0_{suffix},env\);\}}")
            if step + 1 < arity:
                unique(partial, f"{name} curry step {step + 1}", symbol=f"ouro_f{suffix}")
            elif re.search(partial, text) is not None:
                raise RuntimeError(f"extra module pure scope curry parameter {name}")
        if not installed:
            raw = match.group("raw")
            replacements.append((match.start(), match.end(), match.group().replace(
                f"{cache}={raw};", f"{cache}={wrapper}({raw}{argument});", 1)))
    if installed:
        for wrapper in prototypes:
            count = sum(route_wrapper == wrapper for _name, _arity, route_wrapper in routes)
            if text.count(wrapper) != count + int(wrapper in wrappers):
                raise RuntimeError("unexpected module pure scope invocation")
        return text
    replacements.append((include.end(), include.end(), declaration))
    return replace_spans(text, replacements)


_LOWER_CTOR_LOOKUP_DECL = "ouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw);\n"


def hook_lower_ctor_lookup(text: str, module: str, *, installed: bool = False,
                           static_index: StaticSymbolIndex | None = None) -> str:
    if module != "_lo":
        return text
    static_index = StaticSymbolIndex.for_text(text, static_index)

    def unique(pattern: str, label: str, *, symbol: str | None = None):
        matches = (list(re.finditer(pattern, text)) if symbol is None
                   else _static_symbol_matches(text, pattern, static_index.starts, symbol))
        if len(matches) != 1:
            raise RuntimeError("missing, malformed or duplicate lower ctor lookup " + label)
        return matches[0]

    count = unique(
        r"int ouro_export_count_lo\(void\)\{return ([0-9]+);\}", "export count",
    ).group(1)
    unique(r"\bouro_export_count_lo\s*\(void\)\s*\{", "count declaration")
    names = unique(
        r'const char \*ouro_export_name_lo\(int i\)\{switch\(i\)\{'
        r'(?P<rows>(?:\s*case [0-9]+:\s*return "(?:[^"\\]|\\.)*";)*)\s*'
        r'(?:\}\s*return "";\s*\}|default:\s*return "";\s*\}\s*\})',
        "name table",
    ).group("rows")
    values = unique(
        r"ouro_v \*ouro_export_value_lo\(int i\)\{switch\(i\)\{"
        r"(?P<rows>(?:\s*case [0-9]+:\s*return ouro_g[0-9]+\(\);)*)\s*"
        r"(?:\}\s*return 0;\s*\}|default:\s*return 0;\s*\}\s*\})",
        "value table",
    ).group("rows")
    unique(r"\bouro_export_name_lo\s*\(int\s+i\)\s*\{", "name declaration")
    unique(r"\bouro_export_value_lo\s*\(int\s+i\)\s*\{", "value declaration")
    names = re.findall(r'case ([0-9]+):\s*return "((?:[^"\\]|\\.)*)";', names)
    values = re.findall(r"case ([0-9]+):\s*return (ouro_g[0-9]+)\(\);", values)
    indices = [str(index) for index in range(len(names))]
    if (count != str(len(names)) or [row[0] for row in names] != indices
            or [row[0] for row in values] != indices):
        raise RuntimeError("malformed lower ctor lookup export inventory")
    selected = [index for index, label in names if label == "lookup_ctor"]
    if len(selected) != 1:
        raise RuntimeError("missing or duplicate lower ctor lookup export")
    getter = dict(values)[selected[0]]
    if sum(value == getter for _, value in values) != 1:
        raise RuntimeError("aliased lower ctor lookup getter")
    definition_counts = Counter(_base_ver(match[1])[0] for match in STATIC_DEF.finditer(text))
    if definition_counts[getter] != 1:
        raise RuntimeError("missing or duplicate lower ctor lookup getter family")
    gid = getter[len("ouro_g"):]
    cache = "ouro_c" + gid
    unique(rf"\bstatic\s+ouro_v\s*\*\s*{cache}\b", "cache declaration", symbol=cache)
    unique(re.escape(f"static ouro_v *{cache};"), "cache", symbol=cache)
    unique(rf"\bstatic\s+ouro_v\s*\*\s*{getter}\s*\([^;{{]*\)\s*\{{", "getter declaration", symbol=getter)
    raw_pattern = rf"(?P<raw>ouro_(?:clos|fix)\(ouro_f{gid}_,env\))"
    header = (f"static ouro_v *{getter}(void){{ouro_env *env=0;(void)env;"
              f"if({cache}==0){{ouro_static_begin();{cache}=")
    tail = f";ouro_static_end();}}return {cache};}}"
    value_pattern = (rf"ouro_wrap_lower_ctor_lookup\({raw_pattern}\)"
                     if installed else raw_pattern)
    match = unique(re.escape(header) + value_pattern + re.escape(tail), "getter", symbol=getter)
    for step in range(2):
        suffix = "0_" * step + gid + "_"
        function = "ouro_f" + suffix
        if definition_counts[function] != 1:
            raise RuntimeError("missing or duplicate lower ctor lookup curry family")
        raw_header = f"static ouro_v *{function}(ouro_env *env0,ouro_v *arg){{"
        unique(rf"\bstatic\s+ouro_v\s*\*\s*{function}\s*\([^;{{]*\)\s*\{{",
               "curry declaration " + str(step + 1), symbol=function)
        unique(re.escape(raw_header), "curry header " + str(step + 1), symbol=function)
        body_header = raw_header + "ouro_env *env=ouro_cons(arg,env0);(void)env;return "
        unique(re.escape(body_header), "curry capture " + str(step + 1), symbol=function)
        partial = (re.escape(raw_header + "ouro_env *env=ouro_cons(arg,env0);(void)env;return ")
                   + rf"ouro_(?:clos|fix)\(ouro_f0_{suffix},env\);\}}")
        if step == 0:
            unique(partial, "first curry step", symbol=function)
        elif re.search(re.escape(body_header) +
                       rf"ouro_(?:clos|fix)\s*\(\s*ouro_f0_{suffix}(?:_d[0-9]+)?\s*,\s*env\s*\)\s*;\s*\}}",
                       text) is not None:
            raise RuntimeError("extra lower ctor lookup curry parameter")
    include = unique(re.escape('#include "ouro_rt.h"\n'), "runtime include")
    if installed:
        if text.count(_LOWER_CTOR_LOOKUP_DECL) != 1 or text.count("ouro_wrap_lower_ctor_lookup") != 2:
            raise RuntimeError("missing or duplicate lower ctor lookup wrapper")
        return text
    if "ouro_wrap_lower_ctor_lookup" in text:
        raise RuntimeError("lower ctor lookup source is already transformed")
    raw = match.group("raw")
    replacement = match.group().replace(f"{cache}={raw};",
                                       f"{cache}=ouro_wrap_lower_ctor_lookup({raw});", 1)
    return replace_spans(text, [(match.start(), match.end(), replacement),
                                 (include.end(), include.end(), _LOWER_CTOR_LOOKUP_DECL)])


def replace_spans(src: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply disjoint source spans once, retaining the first duplicate span."""
    if not replacements:
        return src
    pieces = []
    seen: set[tuple[int, int]] = set()
    cursor = len(src)
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        if (start, end) in seen:
            continue
        if not 0 <= start <= end <= cursor:
            raise ValueError(f"pack_frontend: invalid or overlapping replacement span {start}:{end}")
        seen.add((start, end))
        pieces.extend((src[end:cursor], replacement))
        cursor = start
    pieces.append(src[:cursor])
    return "".join(reversed(pieces))


def uniquify(src: str) -> str:
    """Rename colliding static function bodies with scoped use-binding.

    Uses between def_i and def_{i+1} bind to version i. Uses after the last
    def are assigned to versions in order so a trailing ouro_case that names
    sibling arms does not collapse every slot onto _dN (print_c emits the
    arms, maybe some mid-parents, then a later case that lists them).
    """
    from collections import defaultdict

    by_name: dict[str, list[re.Match[str]]] = defaultdict(list)
    for m in STATIC_DEF.finditer(src):
        by_name[m.group(1)].append(m)
    dups = {n: ms for n, ms in by_name.items() if len(ms) > 1}
    if not dups:
        return spread_case_arms(src, static_names=by_name)
    uses_by_name: dict[str, list[re.Match[str]]] = {name: [] for name in dups}
    for match in IDENT.finditer(src):
        uses = uses_by_name.get(match.group(0))
        if uses is not None:
            uses.append(match)
    repls: list[tuple[int, int, str]] = []
    for name, ms in dups.items():
        for i, m in enumerate(ms):
            if i:
                repls.append((m.start(1), m.end(1), f"{name}_d{i + 1}"))
        bounds = [m.start(1) for m in ms] + [len(src)]
        def_spans = {(m.start(1), m.end(1)) for m in ms}
        nver = len(ms)
        uses = [
            m
            for m in uses_by_name[name]
            if (m.start(), m.end()) not in def_spans
        ]
        has_between = any(
            bounds[0] <= u.start() < bounds[nver - 1] for u in uses
        )
        later_i = 0
        for m in uses:
            pos = m.start()
            if has_between:
                ver = 0
                for i in range(nver):
                    if bounds[i] <= pos < bounds[i + 1]:
                        ver = i
                        break
            else:
                ver = later_i if later_i < nver else nver - 1
                later_i += 1
            if ver:
                repls.append((m.start(), m.end(), f"{name}_d{ver + 1}"))
    return spread_case_arms(replace_spans(src, repls))


_ARM_REF = re.compile(
    r"ouro_(?:thunk|clos)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
    r"|([A-Za-z_][A-Za-z0-9_]*)\s*(?=,|\})"
)
_D_SUFFIX = re.compile(r"_d(\d+)$")
_CASE_ARR_MARK = "(ouro_v *[]){"
_CASE_ARRAY_BRACE = re.compile(r"[{}]")


def _base_ver(name: str) -> tuple[str, int]:
    m = _D_SUFFIX.search(name)
    if not m:
        return name, 1
    return name[: m.start()], int(m.group(1))


def _iter_case_arrays(src: str):
    """Yield (body_start, body_end, body) for each ouro_case arm array."""
    start = 0
    while True:
        j = src.find("ouro_case(", start)
        if j < 0:
            return
        k = src.find(_CASE_ARR_MARK, j)
        if k < 0:
            return
        if k - j > 4000:
            start = j + 10
            continue
        body_s = k + len(_CASE_ARR_MARK)
        depth = 1
        for brace in _CASE_ARRAY_BRACE.finditer(src, body_s):
            depth += 1 if brace[0] == "{" else -1
            if depth == 0:
                body_e = brace.start()
                yield body_s, body_e, src[body_s:body_e]
                start = brace.end()
                break
        else:
            start = j + 10


def spread_case_arms(src: str, *, static_names: Iterable[str] | None = None) -> str:
    """Give colliding ouro_case arm refs distinct uniquify versions.

    print_c can emit sibling thunks with the same path. After uniquify they
    become foo / foo_d2, but both case slots may still name foo_dN. Spread
    repeated base names across the versions that actually exist, skipping
    the enclosing function so a parent is never used as both of its arms.
    """
    if static_names is None:
        static_names = (match.group(1) for match in STATIC_DEF.finditer(src))
    defined: dict[str, set[int]] = {}
    for name in static_names:
        base, ver = _base_ver(name)
        defined.setdefault(base, set()).add(ver)
    repls: list[tuple[int, int, str]] = []
    for body_s, _body_e, body in _iter_case_arrays(src):
        hits: dict[str, list[re.Match[str]]] = {}
        for am in _ARM_REF.finditer(body):
            name = am.group(1) or am.group(2)
            if not name or name in ("ouro_v",):
                continue
            # Runtime helpers are never match-arm bodies.
            if name in (
                "ouro_thunk",
                "ouro_clos",
                "ouro_app",
                "ouro_ctor",
                "ouro_get",
                "ouro_case",
                "ouro_err",
                "ouro_nat",
                "ouro_bytes",
                "ouro_packed",
            ):
                continue
            base, _ = _base_ver(name)
            hits.setdefault(base, []).append(am)
        for base, arms in hits.items():
            if len(arms) < 2:
                continue
            olds = [(am.group(1) or am.group(2)) for am in arms]
            if len(set(olds)) == len(olds):
                continue
            # Nested False-arm matches can share a path in print_c output.
            # If both slots name the last definition, the prior definition
            # is the True arm and the last definition is the continuation.
            if len(set(olds)) == 1 and len(olds) == 2:
                old = olds[0]
                _b, ver = _base_ver(old)
                prev_ver = ver - 1
                if prev_ver >= 1 and prev_ver in defined.get(base, set()):
                    prev = base if prev_ver == 1 else f"{base}_d{prev_ver}"
                    am = arms[0]
                    if am.group(1):
                        s = am.start(1) + body_s
                        e = am.end(1) + body_s
                    else:
                        s = am.start(2) + body_s
                        e = am.end(2) + body_s
                    if prev != old:
                        repls.append((s, e, prev))
                continue
            # Keep unique references. Use unclaimed definitions for duplicate slots.
            # Any remaining slots use the last definition.
            vers = sorted(defined.get(base, {1}))
            if len(vers) < 2:
                continue
            taken = set()
            unique_vers = []
            for old in olds:
                _, v = _base_ver(old)
                if olds.count(old) == 1:
                    taken.add(v)
                    unique_vers.append(v)
                else:
                    unique_vers.append(None)
            unused = [v for v in vers if v not in taken]
            ui = 0
            for i, am in enumerate(arms):
                if unique_vers[i] is not None:
                    continue
                if ui < len(unused):
                    ver = unused[ui]
                    ui += 1
                else:
                    ver = vers[-1]
                new = base if ver == 1 else f"{base}_d{ver}"
                old = olds[i]
                if new == old:
                    continue
                if am.group(1):
                    s = am.start(1) + body_s
                    e = am.end(1) + body_s
                else:
                    s = am.start(2) + body_s
                    e = am.end(2) + body_s
                repls.append((s, e, new))
    return replace_spans(src, repls)


def uniquify_file(path: str | Path) -> int:
    """In-place uniquify (backend emit / stage_loop). Returns 1 if rewritten."""
    p = Path(path)
    try:
        src = p.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SystemExit(f"pack_frontend: cannot read {p}: {exc}") from exc
    out = uniquify(src)
    if out == src:
        return 0
    try:
        p.write_text(out, encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SystemExit(f"pack_frontend: cannot write {p}: {exc}") from exc
    return 1


def _find_app_close(src: str, start: int) -> int:
    """Find the application's closing parenthesis after its balanced callee."""
    depth = 1
    j = start
    while j < len(src):
        ch = src[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _export_gmap(src: str) -> dict[str, str]:
    names: dict[int, str] = {}
    vals: dict[int, str] = {}
    for m in CASE_NAME.finditer(src):
        names[int(m.group(1))] = m.group(2)
    for m in CASE_VAL.finditer(src):
        vals[int(m.group(1))] = m.group(2)
    out: dict[str, str] = {}
    for idx, name in names.items():
        g = vals.get(idx)
        if g:
            out[name] = g
    return out


def _collect_app_spine(src: str, gpos: int, gname: str) -> tuple[int, int, list[str]] | None:
    """Return (spine_start, spine_end, args) for ouro_app*(gname(), args...)."""
    if src[gpos : gpos + len(gname)] != gname:
        return None
    end = gpos + len(gname)
    if src[end : end + 2] != "()":
        return None
    end += 2
    args: list[str] = []
    pos = gpos
    spine_start = gpos
    while True:
        k = pos
        while k > 0 and src[k - 1] in " \t\n":
            k -= 1
        if k == 0 or src[k - 1] != "(":
            break
        open_paren = k - 1
        if src[max(0, open_paren - 8) : open_paren] != "ouro_app":
            break
        app_start = open_paren - 8
        close = _find_app_close(src, end)
        if close < 0:
            break
        # After the inner expr, the current ouro_app's comma sits just
        # after that inner expr, before the new argument.
        scan = end
        while scan < len(src) and src[scan] in " \t\n":
            scan += 1
        if scan >= len(src) or src[scan] != ",":
            break
        arg_s = scan + 1
        while arg_s < close and src[arg_s] in " \t":
            arg_s += 1
        arg = src[arg_s:close].rstrip()
        args.append(arg)
        end = close + 1
        pos = app_start
        spine_start = app_start
    if not args:
        return None
    return spine_start, end, args


def _getter_call_positions(src: str, getters: Iterable[str]) -> dict[str, list[int]]:
    positions: dict[str, list[int]] = {getter: [] for getter in getters}
    if not positions:
        return positions
    # The shared literal prefix lets re skip text before testing suffixes.
    prefix = "ouro_g"
    suffixes = "|".join(re.escape(getter.removeprefix(prefix)) for getter in positions)
    calls = re.compile(rf"{prefix}({suffixes})\(\)")
    for match in calls.finditer(src):
        positions[prefix + match[1]].append(match.start())
    return positions


def strip_poly_type_apps(src: str) -> tuple[str, int]:
    """Keep only the erased value arguments of known polymorphic helpers."""
    gmap = _export_gmap(src)
    targets: list[tuple[str, int]] = []
    for name, keep in POLY_VALUE_ARITY.items():
        g = gmap.get(name)
        if g:
            targets.append((g, keep))
    positions = _getter_call_positions(src, (gname for gname, _ in targets))

    # Collect replacements from the back so offsets stay valid.
    hits: list[tuple[int, int, str]] = []
    stripped = 0
    for gname, keep in targets:
        for pos in positions[gname]:
            spine = _collect_app_spine(src, pos, gname)
            if spine is None:
                continue
            s0, s1, args = spine
            if len(args) <= keep:
                continue
            kept = args[-keep:]
            rebuilt = gname + "()"
            for arg in kept:
                rebuilt = f"ouro_app({rebuilt},{arg})"
            hits.append((s0, s1, rebuilt))
            stripped += len(args) - keep

    hits.sort(key=lambda h: h[0], reverse=True)
    out = src
    for s0, s1, rebuilt in hits:
        out = out[:s0] + rebuilt + out[s1:]
    return out, stripped


def _is_err5_type(prefix: str) -> bool:
    return prefix.startswith(("ouro_err(5)", "ouro_app(ouro_err(5)"))


def _rebuild_ctor(tag: int, fields: list[str]) -> str:
    n = len(fields)
    if n == 0:
        return f"ouro_ctor({tag},0,0)"
    inner = ",".join(fields)
    return f"ouro_ctor({tag},{n},(ouro_v *[]){{{inner}}})"


_CTOR_DELIMITER = re.compile(r"[{}(),]")


def _ctor_array_spans(src: str) -> dict[int, tuple[int, list[int]]]:
    """Index balanced brace bodies and their direct commas in one source scan.

    Both this index and the field splitter treat punctuation mechanically,
    including punctuation in literals. Ambiguous delimiters use the splitter.
    """
    stack: list[tuple[str, int, list[int]]] = []
    arrays: dict[int, tuple[int, list[int]]] = {}
    for token in _CTOR_DELIMITER.finditer(src):
        char, pos = token.group(), token.start()
        if char in "({":
            stack.append((char, pos, []))
        elif char == ",":
            if stack and stack[-1][0] == "{":
                stack[-1][2].append(pos)
        else:
            if not stack or stack[-1][0] != ("(" if char == ")" else "{"):
                return {}
            opening, start, commas = stack.pop()
            if opening == "{":
                arrays[start] = (pos, commas)
    return {} if stack else arrays


def _trim_span(src: str, start: int, end: int) -> tuple[int, int]:
    while start < end and src[start].isspace():
        start += 1
    while end > start and src[end - 1].isspace():
        end -= 1
    return start, end


def _ctor_field_spans(
    src: str, start: int, limit: int, arrays: dict[int, tuple[int, list[int]]]
) -> tuple[list[tuple[int, int]], int] | None:
    indexed = arrays.get(start - 1)
    if indexed is not None and indexed[0] < limit:
        end, commas = indexed
    else:
        # Preserve the original splitter's behavior on malformed punctuation.
        commas = []
        depth = 0
        end = start
        while end < limit:
            char = src[end]
            if char in "{(":
                depth += 1
            elif char == "}":
                if depth == 0:
                    break
                depth -= 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                commas.append(end)
            end += 1
        else:
            return None
    fields = []
    for comma in commas:
        fields.append(_trim_span(src, start, comma))
        start = comma + 1
    if start < end:
        fields.append(_trim_span(src, start, end))
    return fields, end + 1


def _compact_field_prefix(src: str, start: int, end: int) -> str:
    # Erasure predicates need a short prefix; one extra non-space character
    # distinguishes a complete dummy constructor from a longer expression.
    prefix: list[str] = []
    for index in range(start, end):
        char = src[index]
        if not char.isspace():
            prefix.append(char)
            if len(prefix) == len("ouro_app(ouro_err(5)") + 1:
                break
    return "".join(prefix)


PARSER_UNIT_OWNER = "compiler/parser_min.ouro"
_PARSER_UNIT_CTOR = re.compile(
    r"\bouro_ctor\(0,3,\(ouro_v \*\[\]\)\{ouro_ctor\(0,0,0\),"
    r"ouro_get\(env,(?P<tokens>0|[1-9][0-9]*)\),"
    r"ouro_ctor\(1,1,\(ouro_v \*\[\]\)\{"
    r"ouro_get\(env,(?P<position>0|[1-9][0-9]*)\)\}\)\}\)"
)


def _parser_unit_ctor_spans(
    src: str, arrays: dict[int, tuple[int, list[int]]], owner_ordinal: int | None,
) -> frozenset[tuple[int, int]]:
    """Preserve only the two Unit-valued POk sites in the pipeline cone."""
    empty: frozenset[tuple[int, int]] = frozenset()
    heads = []
    for kind, result in (("name", r"const\s+char\s*\*"),
                         ("value", r"ouro_v\s*\*")):
        pattern = (
            result + r"\s*ouro_export_" + kind
            + r"(?P<suffix>_[A-Za-z0-9_]+)?\s*\(\s*int\s+i\s*\)\s*\{"
        )
        matches = list(re.finditer(pattern, src))
        if len(matches) != 1 or matches[0].end() - 1 not in arrays:
            return empty
        heads.append(matches[0])
    if heads[0].group("suffix") != heads[1].group("suffix"):
        return empty
    bodies = [src[head.end():arrays[head.end() - 1][0]] for head in heads]
    names = list(CASE_NAME.finditer(bodies[0]))
    values = list(CASE_VAL.finditer(bodies[1]))
    if any(len(re.findall(r"\bcase\b", body)) != len(rows)
           for body, rows in zip(bodies, (names, values), strict=True)):
        return empty
    if any(re.fullmatch(r"0|[1-9][0-9]*", row.group(1)) is None
           for row in [*names, *values]):
        return empty
    if (len({row.group(1) for row in names}) != len(names)
            or len({row.group(1) for row in values}) != len(values)
            or {row.group(1) for row in names} != {row.group(1) for row in values}):
        return empty
    labels = {row.group(2) for row in names}
    scoped = any(label.startswith("_ouro_m_") for label in labels)
    if scoped and owner_ordinal is None:
        return empty
    gids = []
    for wanted, tokens, position in (("expect_tag", "0", "2"), ("expect_keyword", "1", "3")):
        if scoped and wanted in labels:
            return empty
        label = f"_ouro_m_{owner_ordinal}_{wanted}" if scoped else wanted
        selected = [row for row in names if row.group(2) == label]
        if len(selected) != 1:
            return empty
        index = selected[0].group(1)
        getter = next(row.group(2) for row in values if row.group(1) == index)
        if sum(row.group(2) == getter for row in values) != 1:
            return empty
        match = re.fullmatch(r"ouro_g(0|[1-9][0-9]*)", getter)
        if match is None:
            return empty
        gids.append((match.group(1), tokens, position))
    if len({gid for gid, _tokens, _position in gids}) != 2:
        return empty
    definitions = list(STATIC_DEF.finditer(src))
    allowed = []
    for gid, tokens, position in gids:
        getter_family = re.compile(r"ouro_g" + gid + r"(?:_d[1-9][0-9]*)?")
        getters = [head for head in definitions if getter_family.fullmatch(head.group(1))]
        if (len(getters) != 1 or getters[0].group(1) != "ouro_g" + gid
                or getters[0].end() - 1 not in arrays):
            return empty
        getter = getters[0]
        getter_body = src[getter.end():arrays[getter.end() - 1][0]]
        expected_getter = (f"ouro_env *env=0;(void)env;if(ouro_c{gid}==0){{ouro_static_begin();"
                           f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);ouro_static_end();}}return ouro_c{gid};")
        if getter_body != expected_getter:
            return empty
        family = re.compile(r"ouro_[ft](?:(?:0|[1-9][0-9]*)_)*" + gid
                            + r"_(?:_d[1-9][0-9]*)?")
        members = [head for head in definitions if family.fullmatch(head.group(1))]
        if (not members or sum(head.group(1) == "ouro_f" + gid + "_"
                               for head in members) != 1
                or len({head.group(1) for head in members}) != len(members)):
            return empty
        candidates = []
        for head in members:
            opening = head.end() - 1
            if opening not in arrays:
                return empty
            end = arrays[opening][0]
            if any(other.start() > head.start() and other.start() < end
                   for other in definitions):
                return empty
            body = src[head.end():end]
            if any(token in body for token in ('"', "'", "/*", "//")):
                return empty
            for match in _PARSER_UNIT_CTOR.finditer(src, head.end(), end):
                if (match.group("tokens"), match.group("position")) != (tokens, position):
                    return empty
                candidates.append(match.span())
        if len(candidates) != 1:
            return empty
        allowed.extend(candidates)
    return frozenset(allowed)


def strip_ctor_type_fields(
    src: str, drop_pair_dummy: bool, *, parser_unit: bool = False,
    parser_min_ordinal: int | None = None,
) -> tuple[str, int]:
    """Drop leftover Type fields, preserving the same constructor rewrite rules.

    `ouro_err(5)` is CInd extracted as a value, never a real field. Parser
    TUs retain the leading Unit in POk triples. The mixed pipeline TU also
    retains its two validated POk Unit sites. Other non-parser sites keep
    the leading dummy check after erasing leading Type fields.

    Unchanged nested fields remain spans into the original source. Only a
    constructor with a dropped field materializes rewritten text; the usual
    strict-validation path does not copy or rescan whole nested subtrees.
    """
    arrays = _ctor_array_spans(src) if "ouro_ctor(" in src else {}
    parser_unit_spans = (_parser_unit_ctor_spans(src, arrays, parser_min_ordinal)
                         if parser_unit else frozenset())

    def rewrite(low: int, high: int) -> tuple[str | None, int]:
        hits: list[tuple[int, int, str]] = []
        stripped = 0
        start = low
        while True:
            pos = src.find("ouro_ctor(", start, high)
            if pos < 0:
                break
            j = pos + len("ouro_ctor(")
            while j < high and src[j] in " \t":
                j += 1
            tag_s = j
            while j < high and src[j].isdigit():
                j += 1
            if tag_s == j:
                start = pos + 1
                continue
            tag = int(src[tag_s:j])
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != ",":
                start = pos + 1
                continue
            j += 1
            while j < high and src[j] in " \t":
                j += 1
            n_s = j
            while j < high and src[j].isdigit():
                j += 1
            if n_s == j:
                start = pos + 1
                continue
            n = int(src[n_s:j])
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != ",":
                start = pos + 1
                continue
            j += 1
            while j < high and src[j] in " \t":
                j += 1
            if n == 0 or not src.startswith("(ouro_v *[])", j, high):
                start = pos + 1
                continue
            j += 12
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != "{":
                start = pos + 1
                continue
            parsed = _ctor_field_spans(src, j + 1, high, arrays)
            if parsed is None:
                start = pos + 1
                continue
            fields, end = parsed
            while end < high and src[end] in " \t":
                end += 1
            if end < high and src[end] == ")":
                end += 1
            values: list[str | None] = []
            dropped = 0
            for a, b in fields:
                value, count = rewrite(a, b)
                values.append(value)
                dropped += count
            keep = 0
            prefix = ""
            while keep < len(fields):
                a, b = fields[keep]
                value = values[keep]
                prefix = (
                    _compact_field_prefix(src, a, b) if value is None
                    else _compact_field_prefix(value, 0, len(value))
                )
                if not _is_err5_type(prefix):
                    break
                keep += 1
                dropped += 1
            if (
                drop_pair_dummy and tag == 0 and len(fields) - keep == 3
                and prefix == "ouro_ctor(0,0,0)"
                and (pos, end) not in parser_unit_spans
            ):
                keep += 1
                dropped += 1
            start = end
            if dropped == 0:
                continue
            new_fields = [
                value if value is not None else src[a:b]
                for (a, b), value in zip(fields[keep:], values[keep:], strict=True)
            ]
            hits.append((pos, end, _rebuild_ctor(tag, new_fields)))
            stripped += dropped
        if not hits:
            return None, 0
        chunks = []
        cursor = low
        for start, end, text in hits:
            chunks.extend((src[cursor:start], text))
            cursor = end
        chunks.append(src[cursor:high])
        return "".join(chunks), stripped

    result, count = rewrite(0, len(src))
    return (src if result is None else result), count


def prefix_blob(src: str, suf: str) -> str:
    return SYM.sub(lambda m: f"ouro_{suf}_{m.group(1)}", src)


def _ctor_span_checks() -> list[tuple[str, bool]]:
    from unittest.mock import patch

    unit = "ouro_ctor(0,0,0)"
    err = "ouro_err(5)"

    def ctor(tag: str, fields: list[str]) -> str:
        return f"ouro_ctor({tag},{len(fields)},(ouro_v *[]){{{','.join(fields)}}})"

    cascade = ctor("0", [ctor("0", [err]), "x", "y"])
    triple = ctor("0", [unit, "x", "y"])
    cases = [
        ("nested erasure then dummy", cascade, True, ctor("0", ["x", "y"]), 2),
        ("parser dummy retained", cascade, False, triple, 1),
        ("leading dummy", triple, True, ctor("0", ["x", "y"]), 1),
        ("nonleading error retained", ctor("1", ["x", err]), True,
         ctor("1", ["x", err]), 0),
        ("nested erasure after a retained field", ctor("1", ["x", ctor("2", [err, "y"])]), True,
         ctor("1", ["x", ctor("2", ["y"])]), 1),
        ("compact error spelling", ctor("1", ["ouro_ \t err(5 )", "x"]), True,
         ctor("1", ["x"]), 1),
        ("Unicode whitespace", ctor("0", ["ouro_ctor(0,\u20030,0)", "x", "y"]),
         True, ctor("0", ["x", "y"]), 1),
        ("Unicode decimal tag", ctor("\u0660", [err, "x"]), True,
         ctor("0", ["x"]), 1),
        ("declared arity does not replace field count", triple.replace(",3,", ",7,"),
         True, ctor("0", ["x", "y"]), 1),
        ("nested commas", ctor("1", [err, "f(x,y)", "{x,y}"]), True,
         ctor("1", ["f(x,y)", "{x,y}"]), 1),
        ("trailing empty field", triple[:-2] + ",})", True,
         ctor("0", ["x", "y"]), 1),
        ("trailing whitespace field", triple[:-2] + ", })", True,
         triple[:-2] + ", })", 0),
        ("unbalanced prefix", ")" + ctor("0", [err]), True, ")" + unit, 1),
        ("missing final parenthesis", triple[:-1], True, ctor("0", ["x", "y"]), 1),
        ("zero arity still scans nested calls", f"ouro_ctor(0,0,{ctor('0', [err])})",
         True, f"ouro_ctor(0,0,{unit})", 1),
        ("surrogate bytes", "\udcff" + ctor("0", [err]), True, "\udcff" + unit, 1),
    ]
    checks = [(name, strip_ctor_type_fields(src, flag) == (expected, count))
              for name, src, flag, expected, count in cases]
    clean = "ouro_nat(7)"
    levels = 96
    for _ in range(levels):
        clean = ctor("1", [unit, clean])
    with (
        patch.object(sys.modules[__name__], "_ctor_array_spans", wraps=_ctor_array_spans) as scan,
        patch.object(sys.modules[__name__], "_compact_field_prefix", wraps=_compact_field_prefix) as prefix,
    ):
        result, count = strip_ctor_type_fields(clean, True)
        checks.append(("one delimiter scan for nested fields",
                       scan.call_count == 1 and result is clean and count == 0))
        checks.append(("only leading fields need erasure prefixes", prefix.call_count == levels))
    try:
        strip_ctor_type_fields("ouro_ctor(\u00b2,1,(ouro_v *[]){x})", True)
    except ValueError:
        checks.append(("invalid decimal remains an error", True))
    else:
        checks.append(("invalid decimal remains an error", False))
    return checks


def _app_spine_checks() -> list[tuple[str, bool]]:
    balanced = 'ouro_app(\n ouro_app(ouro_g1(), wrap("()", x) /* () */) \t, outer(y) )'
    outer_prefix = "ouro_app("
    partial = outer_prefix + "ouro_app(ouro_g1(), wrap(x))"
    inner_span = (len(outer_prefix), len(partial), ["wrap(x)"])
    quoted = 'ouro_app(ouro_app(ouro_g1(), ")"), x)'
    cases = (
        ("balanced callee with a literal and comment", balanced,
         (0, len(balanced), ['wrap("()", x) /* () */', "outer(y)"])),
        ("unclosed outer application keeps the inner span", partial + ", tail", inner_span),
        ("missing outer comma keeps the inner span", partial + " tail)", inner_span),
        ("quoted closing parenthesis ends the inner span", quoted,
         (len(outer_prefix), quoted.index(')"') + 1, ['"'])),
    )
    return [
        (name, _collect_app_spine(src, src.index("ouro_g1()"), "ouro_g1") == expected)
        for name, src, expected in cases
    ]


def _getter_scan_checks() -> list[tuple[str, bool]]:
    unicode_getter = "ouro_g\u0661"
    adjacent = f"xouro_g1()ouro_g12(){unicode_getter}()ouro_g123()ouro_g1()"
    positions = _getter_call_positions(adjacent, ("ouro_g1", "ouro_g12", unicode_getter, "ouro_g1"))
    exports = (
        'case 0:return "length";case 1:return "append";'
        f"case 0:return {unicode_getter}();case 1:return {unicode_getter}();\n"
    )
    call = f"ouro_app(ouro_app(ouro_app({unicode_getter}(),a),b),c)"
    # The second alias uses the original span after the first replacement.
    rewritten = strip_poly_type_apps(exports + call + "123456789012tail")
    expected_positions = {"ouro_g1": [1, 40], "ouro_g12": [10], unicode_getter: [20]}
    expected_rewrite = exports + f"ouro_app({unicode_getter}(),c)tail"
    return [
        ("exact adjacent getter calls", positions == expected_positions),
        ("getter aliases keep equal-span rewrite order", rewritten == (expected_rewrite, 3)),
    ]


def _selftest() -> int:
    """Tiny rewrite checks for 2/3/4-arg poly spines."""
    blob = """
int ouro_export_count_x(void){return 4;}
const char *ouro_export_name_x(int i){
  switch(i){
    case 0: return "bindParseResult";
    case 1: return "bindValue";
    case 2: return "isJust";
    case 3: return "isNothing";
    default: return "";
  }
}
ouro_v *ouro_export_value_x(int i){
  switch(i){
    case 0: return ouro_g280();
    case 1: return ouro_g332();
    case 2: return ouro_g244();
    case 3: return ouro_g245();
    default: return 0;
  }
}
static ouro_v *ouro_g280(void){return 0;}
static ouro_v *ouro_g332(void){return 0;}
static ouro_v *ouro_g244(void){return 0;}
static ouro_v *ouro_g245(void){return 0;}
static ouro_v *use(void){
  return ouro_app(ouro_app(ouro_app(ouro_app(ouro_g280(),ouro_err(5)),ouro_ctor(0,0,0)),r),f);
}
static ouro_v *use2(void){
  return ouro_app(ouro_app(ouro_app(ouro_app(ouro_g332(),ouro_err(5)),pred),r),k);
}
static ouro_v *use3(void){
  return ouro_app(ouro_app(ouro_g244(),ouro_ctor(0,0,0)),m);
}
static ouro_v *use4(void){
  return ouro_app(ouro_app(ouro_g245(),ouro_ctor(0,0,0)),m);
}
"""
    out, n = strip_poly_type_apps(blob)
    checks = [
        ("bindParseResult 4->2", "ouro_app(ouro_app(ouro_g280(),r),f)" in out),
        ("bindValue 4->3", "ouro_app(ouro_app(ouro_app(ouro_g332(),pred),r),k)" in out),
        ("isJust 2->1", "ouro_app(ouro_g244(),m)" in out),
        ("isNothing 2->1", "ouro_app(ouro_g245(),m)" in out),
        ("dropped leftover Type", "ouro_err(5)" not in out and "ouro_ctor(0,0,0)" not in out),
        ("stripped count", n == 5),
    ]
    ctor_in = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),ouro_get(env,2),ouro_get(env,1)})"
    ctor_out, cn = strip_ctor_type_fields(ctor_in, drop_pair_dummy=True)
    checks.append(("MkPair dummy0 drop", ctor_out == "ouro_ctor(0,2,(ouro_v *[]){ouro_get(env,2),ouro_get(env,1)})" and cn == 1))
    pok = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),toks,pos})"
    pok_out, pn = strip_ctor_type_fields(pok, drop_pair_dummy=False)
    checks.append(("POk Unit kept", pok_out == pok and pn == 0))
    errf = "ouro_ctor(0,3,(ouro_v *[]){ouro_app(ouro_err(5),ouro_ctor(0,0,0)),ouro_ctor(0,0,0),x})"
    err_out, en = strip_ctor_type_fields(errf, drop_pair_dummy=False)
    checks.append(("ERR5 field drop", err_out == "ouro_ctor(0,2,(ouro_v *[]){ouro_ctor(0,0,0),x})" and en == 1))
    nested_array_body = "outer((ouro_v *[]){left,right}),last"
    nested_array = "ouro_case(s,2," + _CASE_ARR_MARK + nested_array_body + "})"
    for label, prefix in (("nested case array offsets", ""),
                          ("case array after unclosed array", "ouro_case(s,1," + _CASE_ARR_MARK + "unclosed, ")):
        array_source = prefix + nested_array
        body_start = array_source.index(nested_array_body)
        checks.append((label, list(_iter_case_arrays(array_source)) == [
            (body_start, body_start + len(nested_array_body), nested_array_body),
        ]))
    arms = (
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return a;}\n"
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return e->v;}\n"
        "static ouro_v *use(void){return ouro_case(s,2,(ouro_v *[]){foo,foo});}\n"
    )
    uout = uniquify(arms)
    checks.append(
        (
            "uniquify after-last arms",
            "foo_d2" in uout
            and "ouro_case(s,2,(ouro_v *[]){foo,foo_d2})" in uout,
        )
    )
    # Mid-use plus a later nested-arg ouro_case that named both arms _d3.
    mixed = (
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(8,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(ouro_t1_1_,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(11,0,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){"
        "return ouro_case(ouro_app(ouro_g76(),x),2,(ouro_v *[]){"
        "ouro_thunk(ouro_t1_1_,e),ouro_thunk(ouro_t1_1_,e)});}\n"
    )
    mout = uniquify(mixed)
    checks.append(
        (
            "uniquify mid+after-last TSemi",
            "ouro_t1_1__d2" in mout
            and "ouro_t1_1__d3" in mout
            and "ouro_thunk(ouro_t1_1__d2,e),ouro_thunk(ouro_t1_1__d3,e)" in mout
            and "ouro_ctor(11,0,0)" in mout,
        )
    )
    # Live tok_simple1 shape: a *different* parent case names both arms as
    # the last version of a 3-def path (TBar, TSemi, next-match).
    live = (
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(8,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(ouro_t1_1_,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(11,0,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(14,0,0);}\n"
        "static ouro_v *parent(ouro_env *e,ouro_v *a){"
        "return ouro_case(ouro_app(ouro_g76(),x),2,(ouro_v *[]){"
        "ouro_thunk(ouro_t1_1_,e),ouro_thunk(ouro_t1_1_,e)});}\n"
    )
    lout = uniquify(live)
    checks.append(
        (
            "spread last-version pair = prev, last",
            "ouro_thunk(ouro_t1_1__d2,e),ouro_thunk(ouro_t1_1__d3,e)" in lout
            and "ouro_ctor(11,0,0)" in lout,
        )
    )
    nested = (
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return a;}\n"
        "static ouro_v *foo_d2(ouro_env *e,ouro_v *a){return e->v;}\n"
        "static ouro_v *use(void){return ouro_case(ouro_app(g(),x),2,"
        "(ouro_v *[]){ouro_thunk(foo_d2,e),ouro_thunk(foo_d2,e)});}\n"
    )
    nout = spread_case_arms(nested)
    checks.append(
        (
            "spread nested ouro_case first-arg",
            "ouro_thunk(foo,e),ouro_thunk(foo_d2,e)" in nout and uniquify(nested) == nout,
        )
    )
    interleaved = (
        "static ouro_v *before(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(1,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(2,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(3,0,0);}\n"
        "static ouro_v *mid2(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(4,0,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(5,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(6,0,0);}\n"
        "static ouro_v *after(void){return ouro_case(ouro_app(g(),x),3,"
        "(ouro_v *[]){ouro_thunk(alpha,e),ouro_thunk(alpha,e),"
        "ouro_ctor(0,1,(ouro_v *[]){ouro_thunk(beta,e)})});}\n"
        "static ouro_v *tail(void){return ouro_case(s,3,"
        "(ouro_v *[]){beta,ouro_thunk(beta,e),beta});}\n"
        "static ouro_v *prefix(ouro_env *e,ouro_v *a){return ouro_thunk(alpha_extra,e);}\n"
    )
    interleaved_expected = (
        "static ouro_v *before(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(1,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(2,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha_d2(ouro_env *e,ouro_v *a){return ouro_ctor(3,0,0);}\n"
        "static ouro_v *mid2(void){return ouro_thunk(alpha_d2,0);}\n"
        "static ouro_v *beta_d2(ouro_env *e,ouro_v *a){return ouro_ctor(4,0,0);}\n"
        "static ouro_v *alpha_d3(ouro_env *e,ouro_v *a){return ouro_ctor(5,0,0);}\n"
        "static ouro_v *beta_d3(ouro_env *e,ouro_v *a){return ouro_ctor(6,0,0);}\n"
        "static ouro_v *after(void){return ouro_case(ouro_app(g(),x),3,"
        "(ouro_v *[]){ouro_thunk(alpha_d2,e),ouro_thunk(alpha_d3,e),"
        "ouro_ctor(0,1,(ouro_v *[]){ouro_thunk(beta,e)})});}\n"
        "static ouro_v *tail(void){return ouro_case(s,3,"
        "(ouro_v *[]){beta_d2,ouro_thunk(beta_d3,e),beta_d3});}\n"
        "static ouro_v *prefix(ouro_env *e,ouro_v *a){return ouro_thunk(alpha_extra,e);}\n"
    )
    interleaved_out = uniquify(interleaved)
    checks.append(("uniquify interleaved scoped names and mixed nested arms",
                   interleaved_out == interleaved_expected))
    checks.extend(_app_spine_checks())
    checks.extend(_getter_scan_checks())
    checks.extend(_ctor_span_checks())
    bad = [name for name, ok in checks if not ok]
    if bad:
        print("pack_frontend selftest FAIL", bad, file=sys.stderr)
        if interleaved_out != interleaved_expected:
            print("--- interleaved expected ---", file=sys.stderr)
            print(interleaved_expected, file=sys.stderr)
            print("--- interleaved actual ---", file=sys.stderr)
            print(interleaved_out, file=sys.stderr)
        print("--- mixed ---", file=sys.stderr)
        print(mout, file=sys.stderr)
        print("--- nested ---", file=sys.stderr)
        print(nout, file=sys.stderr)
        print(out, file=sys.stderr)
        return 1
    print(f"pack_frontend selftest OK stripped={n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", required=False)
    ap.add_argument(
        "pieces",
        nargs="*",
        help="SUFFIX:path pairs, e.g. lx:_build/fe/lx.c",
    )
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--uniquify-only",
        metavar="FILE",
        help="In-place uniquify + spread_case_arms (backend emit).",
    )
    ap.add_argument(
        "--mechanical",
        action="store_true",
        help="Prefix + uniquify only (default). Do not run leftover detectors.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any leftover Type app would need stripping.",
    )
    ap.add_argument("--parser-min-ordinal", type=int, help="Source ordinal in the ordered pipeline cone.")
    args = ap.parse_args()
    if args.parser_min_ordinal is not None and args.parser_min_ordinal < 0:
        ap.error("--parser-min-ordinal must be nonnegative")
    if args.selftest:
        return _selftest()
    if args.uniquify_only:
        uniquify_file(args.uniquify_only)
        return 0
    if not args.output or not args.pieces:
        ap.error("output and SUFFIX:path pieces are required")
    out_path = Path(args.output)
    chunks: list[str] = [
        "/* Generated frontend pack: split O8 cones, prefixed statics.\n"
        "   Do not hand-edit. Regenerate with scripts/emit_frontend.sh. */\n"
    ]
    dropped_total = 0
    for spec in args.pieces:
        if ":" not in spec:
            print(f"pack_frontend: expected SUFFIX:path, got {spec}", file=sys.stderr)
            return 2
        suf, path = spec.split(":", 1)
        try:
            text = Path(path).read_text(encoding="utf-8", errors="surrogateescape")
        except OSError as exc:
            print(f"pack_frontend: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        if "ouro_export_count_" not in text:
            print(f"pack_frontend: {path} has no export table", file=sys.stderr)
            return 2
        text = uniquify(text)
        if args.strict:
            _, dropped = strip_poly_type_apps(text)
            drop_pair = suf not in ("pa", "pb", "pf")
            _, dropped_c = strip_ctor_type_fields(
                text, drop_pair_dummy=drop_pair, parser_unit=suf == "pl",
                parser_min_ordinal=args.parser_min_ordinal,
            )
            dropped_total += dropped + dropped_c
        chunks.append(f"\n/* ---- frontend TU module={suf} ---- */\n")
        chunks.append(prefix_blob(text, suf))
        chunks.append("\n")
        del text
    if args.strict and dropped_total > 0:
        print(
            f"pack_frontend: STRICT FAIL leftover_type_apps={dropped_total} "
            "(extract.ouro should have dropped these)",
            file=sys.stderr,
        )
        return 3
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", errors="surrogateescape") as output:
            output.writelines(chunks)
    except OSError as exc:
        print(f"pack_frontend: cannot write {out_path}: {exc}", file=sys.stderr)
        return 2
    mode = "strict" if args.strict else "mechanical"
    print(
        f"pack_frontend: wrote {out_path} bytes={out_path.stat().st_size} "
        f"leftover_type_apps={dropped_total} mode={mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
