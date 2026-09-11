"""Inject canonical checker and surface faults into isolated source copies.

The canonical Ouro law executable supplies exact independent expectations.
Every mutation must build, run, and fail its required semantic laws after a
clean baseline. Crashes, stale targets, unrelated findings, and input drift
never establish a kill. Surface/tool faults retain their own exact properties.
"""
from __future__ import annotations

import os
import shutil
import stat
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from ourosmith import ROOT, generator_hash
from ourosmith.host import prepare_tools

if TYPE_CHECKING:
    from pathlib import Path
    from ourosmith.report import Report

FAULTS_KIND = "ouro.smith-faults.v1"


@dataclass(frozen=True)
class Fault:
    id: str
    target: str
    file: str  # path relative to the repository root
    old: str
    new: str
    description: str
    # Exact properties that must notice the intended semantic defect.
    expect: tuple[str, ...] = ()
    case: str = ""
    extra_patches: tuple[tuple[str, str, str], ...] = ()
    legacy: tuple[str, ...] = ()


# Count validation and the exhaustive branch walk independently enforce coverage.
_COVERAGE_WALK = """def infer_check_branches
    (infer : CheckEnvironment -> List CoreTerm -> InferGoal -> CheckResult CoreTerm)
    (fuel : Nat) (sig : CheckEnvironment) (ctx : List CoreTerm)
    (ind : Nat) (nparams : Nat) (nindices : Nat)
    (args : List CoreTerm) (predicate : CoreTerm)
    : List Ctor -> List Nat -> List CoreTerm -> Nat -> CheckResult Unit :=
  fix branches (ctors : List Ctor) (arities : List Nat)
      (bodies : List CoreTerm) (index : Nat) : CheckResult Unit :=
    match ctors with
    | Nil =>
        match arities, bodies with
        | Nil, Nil => CheckOk Unit MkUnit
        | Nil, Cons _ _ => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        | Cons _ _, Nil => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        | Cons _ _, Cons _ _ => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        end
    | Cons ctor rest =>
        match arities, bodies with
        | Cons arity arities', Cons body bodies' =>
            check_bind CoreTerm Unit
              (infer_branch_expected_checked fuel sig ind nparams nindices args predicate index arity ctor)
              (fun (expected : CoreTerm) =>
                check_bind Unit Unit (check_term_using infer sig fuel ctx body expected)
                  (fun (_branch : Unit) => branches rest arities' bodies' (S index)))
        | Nil, Nil => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        | Nil, Cons _ _ => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        | Cons _ _, Nil => CheckErr Unit (CheckMalformedCore CheckCaseMetadata)
        end
    end;

"""

OBSOLETE_CHECKER_CONTRACTS = (
    {"id": 'py-axiom-tracking-off', "status": "obsolete-owner",
     "reason": 'uses_axioms and axiom_dependent were proof-query metadata and OCaml memo eligibility owned by the retired replay/kernel implementations. Canonical Entry, DeclarationResult and CheckedProgram have no such report or memo policy. Their removal does not permit an opaque axiom body to reduce.',
     "retained_control": "CTL.opaque-neutral"},
    {"id": 'ml-axiom-tracking-off', "status": "obsolete-owner",
     "reason": 'uses_axioms and axiom_dependent were proof-query metadata and OCaml memo eligibility owned by the retired replay/kernel implementations. Canonical Entry, DeclarationResult and CheckedProgram have no such report or memo policy. Their removal does not permit an opaque axiom body to reduce.',
     "retained_control": "CTL.opaque-neutral"},
)


FAULTS: tuple[Fault, ...] = (
    Fault(
        'ouro-cumul-sort-any', "checker", 'compiler/file_elab_term.ouro',
        '| Just u, Just v => CheckOk Bool (compiler_le_nat u v)',
        '| Just u, Just v => CheckOk Bool True',
        'Sort cumulativity requires actual universe <= expected universe.', ('CHK.sort-cumul',),
        legacy=('py-cumul-sort-any', 'ml-cumul-sort-any'),
    ),
    Fault(
        'ouro-termination-off', "checker", 'compiler/file_elab_infer.ouro',
        '(check_termination_checked rec_arg arity fuel body)',
        '(CheckOk Unit MkUnit)',
        'Every typed fixpoint body is checked for structural descent before inference succeeds.', ('CHK.termination',),
        legacy=('py-termination-off', 'ml-termination-off'),
    ),
    Fault(
        'ouro-nested-all-parameters-small', "checker", 'compiler/file_elab_term.ouro',
        'match eqNat index nested_rec with',
        'match True with',
        'Only the nested structural parameter inherits a smaller-than witness; accumulators do not.', ('CHK.nested-other-parameter',),
        legacy=('py-nested-all-parameters-small', 'ml-nested-all-parameters-small'),
    ),
    Fault(
        'ouro-conv-ignore-spine', "checker", 'compiler/file_elab_core.ouro',
        '| CApp f a => eq_term_pair eq_term fuel 2 f a t2',
        '| CApp f _ => match eq_pair_head 2 t2 with\n        | YesEqPair other _ => eq_term fuel f other\n        | NoEqPair => Normalized Bool False\n        end',
        'Applications with equal neutral heads still compare their arguments.', ('CHK.application-arguments',),
        legacy=('py-conv-ignore-spine', 'ml-conv-ignore-spine'),
    ),
    Fault(
        'ouro-positivity-off', "checker", 'compiler/file_elab_positive.ouro',
        "check_and (positive_type_checked_indexed fuel' sig known focus domain)",
        'check_and (CheckOk Bool True)',
        'A constructor field may not contain its inductive in a negative position.', ('CHK.positivity',),
        legacy=('py-positivity-off', 'ml-positivity-off'),
    ),
    Fault(
        'ouro-iota-off', "checker", 'compiler/file_elab_core.ouro',
        'normalize_case_constructor reduce info branches ind index nparams arguments',
        'normalize_stuck_case head info motive value branches',
        'A case over a constructor evaluates its selected branch.', ('CHK.iota-constructor',),
        legacy=('py-iota-off',),
    ),
    Fault(
        'ouro-iota-keep-params', "checker", 'compiler/file_elab_core.ouro',
        'reduce (mk_app branch (drop CoreTerm nparams arguments))',
        'reduce (mk_app branch arguments)',
        'Iota applies constructor fields to the branch after dropping uniform parameters.', ('CHK.iota-parameters',),
        legacy=('ml-iota-keep-params',),
    ),
    Fault(
        'ouro-prim-concat-swap', "checker", 'compiler/string_nf_bytes.ouro',
        '(fun (_valid : Unit) => string_nf_append_bytes fuel left right)',
        '(fun (_valid : Unit) => string_nf_append_bytes fuel right left)',
        'Checked String concatenation preserves operand order and all byte values.', ('CHK.string-concat',),
        legacy=('py-prim-concat-swap', 'ml-prim-concat-swap'),
    ),
    Fault(
        'ouro-lambda-annotation-off', "checker", 'compiler/file_elab_infer.ouro',
        "(check_convertible_indexed fuel sig annotation domain)",
        '(CheckOk Unit MkUnit)',
        'An explicit lambda annotation must be convertible to its expected Pi domain.', ('CHK.lambda-annotation',),
        legacy=('py-lambda-annotation-off', 'ml-lambda-annotation-off'),
    ),
    Fault(
        'ouro-duplicate-global-off', "checker", 'compiler/file_elab.ouro',
        'match declaration_name_conflict_indexed item sig with',
        'match False with',
        'Declaration replay rejects a global name already present in the accepted environment.', ('CHK.duplicate-global',),
        legacy=('py-duplicate-global-off', 'ml-duplicate-global-off'),
    ),
    Fault(
        'ouro-coverage-off', "checker", 'compiler/file_elab_infer.ouro',
        '(andb (eqNat (length CoreTerm bodies) (length Ctor ctors))\n                        (eqNat (length Nat arities) (length Ctor ctors)))',
        'True',
        'A case has exactly one branch and arity entry for each constructor.', ('CHK.case-coverage-missing', 'CHK.case-coverage-extra'),
        extra_patches=(("compiler/file_elab_infer.ouro", _COVERAGE_WALK,
                        _COVERAGE_WALK.replace("CheckErr Unit (CheckMalformedCore CheckCaseMetadata)",
                                               "CheckOk Unit MkUnit")),),
        legacy=('py-coverage-off', 'ml-coverage-off'),
    ),
    Fault("fe-lambda-annotation-off", "frontend", "compiler/file_elab_infer.ouro",
          "(check_convertible_indexed fuel sig annotation domain)", "(CheckOk Unit MkUnit)",
          "source lambda annotations are ignored", ("lambda-domain",), "mutation:lambda-domain"),
    Fault("fmt-trailing-space-off", "fmt", "tools/fmt_pipeline.ouro",
          "fixContent (fixPipeSpace (stripTrailingWS (expandTabs line)))",
          "fixContent (fixPipeSpace (expandTabs line))",
          "formatter retains trailing whitespace", ("fmt-roundtrip",), "positive"),
    Fault("lint-hole-off", "lint", "compiler/lint.ouro",
          "| AHole id => wcons (WHole id) wnil", "| AHole _ => wnil",
          "linter ignores holes", ("lint-hole",), "mutation:lint-hole"),
    Fault("fix-rounds-off", "fix", "tools/fix/pipeline.ouro",
          "def fx_rounds : Nat := 8;", "def fx_rounds : Nat := 0;",
          "fixer performs no rewrite rounds", ("fix-check-dirty", "fix-dead-let"), "recipe:fixer"),
    Fault("doc-signature-off", "doc", "tools/doc_model.ouro",
          'str_cat3 "```" (str_concat "\\n" (decl_sig d))', 'str_cat3 "```" "\\n"',
          "documentation omits declaration signatures", ("doc-signature-comment",), "recipe:documentation"),
    Fault("lsp-line-shift", "lsp", "tools/lsp_model.ouro",
          '[ MkPair String Json "line" (json_num line)', '[ MkPair String Json "line" (json_num (S line))',
          "LSP definition positions are shifted by one line", ("lsp-definition",), "recipe:language_server"),
    Fault("runtime-nat-successor", "runtime", "runtime/ouro_eval_main.c",
          "depth += cur->n;", "depth += cur->n + 1;",
          "native natural-number rendering adds one successor", ("runtime-reference",), "positive"),
    Fault("manifest-crash-as-reject", "test", "tools/test/manifest.ouro",
          "| False => eq_nat (proc_code result) (S Z)", "| False => notb (proc_ok result)",
          "manifest treats a crashed checker as the required rejection", ("manifest-status-139",), "recipe:manifest_contract"),
    Fault("eval-string-shims-off", "wrapper", "scripts/ouro1.sh",
          'OURO_EMIT_IO_SHIMS=1 "$COMPILER" "$wrap"', '"$COMPILER" "$wrap"',
          "eval omits the primitive implementations needed by pure string expressions", ("eval-reference",), "recipe:compiler_parity"),
    Fault("analyzer-truncated-walk", "analyzer", "tools/analyze/ast.ouro",
          "end) (ast_size root) root;\n\n-- Variable occurrence", "end) 256 root;\n\n-- Variable occurrence",
          "AST traversal silently truncates a valid deep path", ("analyzer-ast",), "recipe:analyzer_ast"),
    Fault("cache-source-digest-off", "cache", "scripts/selfhost_module_cache.py",
          "return FileDigest(rel(p), sha256_file(p), st.st_size)", 'return FileDigest(rel(p), "0" * 64, st.st_size)',
          "module cache ignores equal-size source changes", ("module-cache-dependency-invalidation",), "recipe:module_cache"),
)


@dataclass
class FaultResult:
    fault: Fault
    status: str  # killed | survived | stale | unbuildable | baseline-dirty
    findings: int = 0
    caught_by: list[str] = field(default_factory=list)
    detail: str = ""
    seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.fault.id,
            "target": self.fault.target,
            "file": self.fault.file,
            "description": self.fault.description,
            "expect": list(self.fault.expect),
            "legacy": list(self.fault.legacy),
            "status": self.status,
            "findings": self.findings,
            "caught_by": self.caught_by,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
        }


class StaleFault(Exception):
    pass


def apply_fault(text: str, fault: Fault) -> str:
    if not fault.old or fault.old == fault.new:
        raise StaleFault(f"{fault.id}: empty or ineffective source mutation")
    count = text.count(fault.old)
    if count != 1:
        raise StaleFault(f"{fault.id}: expected exactly one occurrence of the target text in {fault.file}, found {count}")
    return text.replace(fault.old, fault.new)


def fault_texts(fault: Fault, root: Path) -> dict[str, str]:
    """Apply every exact patch in memory before writing an isolated source copy."""
    from dataclasses import replace

    changed: dict[str, str] = {}
    for filename, old, new in ((fault.file, fault.old, fault.new), *fault.extra_patches):
        if filename not in changed:
            changed[filename] = read_text(root / filename)
        changed[filename] = apply_fault(changed[filename], replace(fault, file=filename, old=old, new=new))
    return changed


def check_catalogue() -> list[str]:
    """Check every live source anchor, including redundant checker guards."""
    from ourosmith.checker_faults import LAW_EXPECTATIONS

    problems: list[str] = []
    seen: set[str] = set()
    for fault in FAULTS:
        if fault.id in seen:
            problems.append(f"duplicate fault id {fault.id}")
        seen.add(fault.id)
        if fault.target not in {"checker", "frontend", "fmt", "lint", "fix", "doc", "lsp", "runtime", "cache", "analyzer", "test", "wrapper"}:
            problems.append(f"{fault.id}: unknown target {fault.target}")
        if not fault.expect:
            problems.append(f"{fault.id}: detecting properties are empty")
        if fault.target == "checker" and any(name not in LAW_EXPECTATIONS or not name.startswith("CHK.") for name in fault.expect):
            problems.append(f"{fault.id}: unknown canonical detecting law")
        try:
            fault_texts(fault, ROOT)
        except (OSError, StaleFault) as exc:
            problems.append(str(exc))
    return problems


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# Scratch copies ------------------------------------------------------------


def remove_scratch(path: Path) -> None:
    resolved = path.resolve()
    allowed = (ROOT / "_build/smith").resolve()
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise RuntimeError(f"mutant cleanup outside _build/smith: {resolved}")

    def writable_retry(function, filename, error):
        if not isinstance(error[1], PermissionError):
            raise error[1]
        # Dune action stamps can be read-only on Windows. Changes stay inside
        # our resolved scratch root.
        os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
        function(filename)

    if path.exists():
        shutil.rmtree(path, onerror=writable_retry)


# Running -------------------------------------------------------------------


def caught_by(report: Report) -> list[str]:
    tags: set[str] = set()
    for f in report.findings:
        tags.add(f"{f.layer}:{f.prop}")
    return sorted(tags)


def detected(fault: Fault, report: Report) -> bool:
    return any(f.prop in fault.expect and f.classification in
               {"property-violation", "wrong-accept", "wrong-reject", "wrong-class", "divergence"}
               for f in report.findings)


def run_faults(
    *,
    config: Any,
    out: Path,
    compiler: Path,
    timeout_s: float,
    memory_mb: int,
    only: Optional[set[str]] = None,
    targets: Optional[set[str]] = None,
    log=print,
) -> dict[str, Any]:
    """Run selected canonical and surface faults; every non-kill fails the run."""
    from ourosmith.checker_faults import run_checker_campaign
    from ourosmith.provenance import begin, binary_state, git, source_state

    started = time.perf_counter()
    provenance = begin()
    status_before = git("status", "--short")
    out.mkdir(parents=True, exist_ok=True)
    problems = check_catalogue()
    selected = [fault for fault in FAULTS if (only is None or fault.id in only)
                and (targets is None or fault.target in targets)]
    if only is not None:
        problems.extend(f"unknown fault id {name}" for name in sorted(only - {fault.id for fault in FAULTS}))
    if targets is not None:
        problems.extend(f"unknown fault target {name}" for name in sorted(targets - {fault.target for fault in FAULTS}))
    tool_failure, tools, toolchain = None, {}, {}
    if any(fault.case for fault in selected):
        try:
            tools, toolchain = prepare_tools(out / "tools-build", compiler)
        except (OSError, ValueError) as error:
            tool_failure = str(error)
    if tool_failure:
        problems.append(f"surface tools unavailable: {tool_failure}")
    original_binaries = [compiler.resolve()]
    if any(fault.case for fault in selected) and not tool_failure:
        original_binaries.extend(tools.values())
    original_binaries = list(dict.fromkeys(original_binaries))
    provenance["binaries"] = binary_state(original_binaries)

    campaign = run_checker_campaign([fault for fault in selected if fault.target == "checker"], out,
                                    compiler=compiler, timeout_s=timeout_s, memory_mb=memory_mb, log=log)
    baseline = campaign["baseline"]
    baseline_clean = baseline["status"] == "clean"
    results = list(campaign["faults"])
    for fault in selected:
        if not fault.case:
            continue
        from ourosmith.surface_faults import run_surface_fault

        result = (FaultResult(fault, "unbuildable", detail=tool_failure) if tool_failure else
                  run_surface_fault(fault, out, timeout_s=timeout_s, memory_mb=memory_mb, overrides=tools))
        results.append(result)
        log(f"OURO_SMITH: FAULT {fault.id} {result.status} findings={result.findings} {result.detail}")
    order = {fault.id: index for index, fault in enumerate(selected)}
    results.sort(key=lambda result: order[result.fault.id])
    status_after = git("status", "--short")
    if status_before != status_after or provenance["source"] != source_state():
        problems.append("working tree changed during fault injection")
    if provenance["binaries"] != binary_state(original_binaries):
        problems.append("original binaries changed during fault injection")
    if not campaign["unchanged"]:
        problems.append("checker inputs changed during fault injection")
    passed = (bool(selected) and baseline_clean and [result.fault.id for result in results] == [fault.id for fault in selected]
              and all(result.status == "killed" for result in results) and not problems)
    return {
        "kind": FAULTS_KIND, "pass": passed, "profile": config.profile,
        "generator_hash": generator_hash(), "provenance": provenance,
        "surface_toolchain": toolchain,
        "working_tree": {"before": status_before.splitlines(), "after": status_after.splitlines(),
                         "unchanged": status_before == status_after},
        "seeds": list(config.seeds),
        "baseline": {"clean": baseline_clean, "findings": len(baseline.get("failed_laws", [])),
                     "skips": 0 if baseline_clean else 1, "seconds": round(baseline.get("seconds", 0), 3),
                     "evidence": baseline},
        "checker": {key: value for key, value in campaign.items() if key not in {"faults", "baseline"}},
        "obsolete_checker_contracts": OBSOLETE_CHECKER_CONTRACTS,
        "catalogue_problems": problems,
        "summary": {
            "faults": len(results), "killed": sum(result.status == "killed" for result in results),
            "survived": sum(result.status == "survived" for result in results),
            "stale": sum(result.status == "stale" for result in results),
            "unbuildable": sum(result.status == "unbuildable" for result in results),
            "checker": sum(result.fault.target == "checker" for result in results),
            "targets": {target: sum(result.fault.target == target for result in results)
                        for target in sorted({fault.target for fault in selected})},
        },
        "faults": [result.to_json() for result in results],
        "timing_s": {"total": round(time.perf_counter() - started, 3)},
    }
