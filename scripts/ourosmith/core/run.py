"""Native Smith orchestration; semantic checking and expected terms live in Ouro."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from ourosmith import generator_hash
from ourosmith.report import Finding

LAYER = "kernel"
RECIPE_KIND = "ouro.smith-native-recipe.v1"
OPERATIONS = """case-nat-field case-bool-branch case-enum-coverage case-option-parameter
case-list-parameters-and-fields case-pair-field-order case-wrap-field case-tree-fields
case-box1-universe case-nested-pair-field-binders string-concat-order string-length-bytes
string-slice-clamped string-equality string-of-nat-decimal string-to-codes string-of-codes
string-neutral-argument polymorphic-option polymorphic-list polymorphic-pair
polymorphic-option-application polymorphic-list-application polymorphic-pair-application
nested-fix-strict nested-fix-nonzero-rec-arg nested-fix-eta-short""".split()
RELATIONS = """alpha-fix-display-name eta-fix eta-polymorphic let-inline let-type-binder
distinct-constructors concat-distinct-order sort-cumulative sort-cumulative-reverse
pi-codomain-cumulative pi-codomain-reverse pi-domain-invariant""".split()
CONTROLS = "covariant-option-nesting covariant-list-nesting earlier-inductive-reference".split()
NEGATIVES = """type-mismatch-def type-mismatch-argument type-mismatch-parameter
lambda-annotation-mismatch sort-level-too-big not-pi sort-expected not-inductive coverage
case-arity case-wrong-inductive case-branch-count ctor-nparams ctor-index
unbound-global-constant unbound-global-inductive forward-reference duplicate-global-axiom
duplicate-global-inductive positivity-negative positivity-nested-contravariant universe termination
termination-nested-unchanged-initial termination-nested-growing-inner
termination-nested-growing-other-parameter termination-nested-captured-unchanged
termination-nested-partial-escape termination-nested-argument-escape fix-arity fix-rec-arg-range""".split()
FORMS = ("beta", "let", "polymorphic-id", "polymorphic-const", "nat-case", "structural-fold", "extra-argument-fold", "higher-order")


@dataclass
class CoreConfig:
    seeds: list[int]
    profile: str
    depth: int = 4
    max_defs: int = 4
    shrink_budget: int = 60
    replay_prefix: str = "python scripts/ouro_smith.py"


@dataclass
class Failure:
    prop: str
    classification: str
    detail: str
    expected: str = "native property holds"

    @property
    def identity(self):
        # Core input rendering is retained in the finding, but shrinking may
        # change that rendering. Preserve the exact law and diagnostic prefix.
        return self.prop, self.classification, self.detail.split(" input=", 1)[0]


def recipe(config, seed, digest=None):
    return {"kind": RECIPE_KIND, "profile": config.profile, "seed": seed,
            "depth": config.depth, "max_defs": config.max_defs,
            "generator_hash": generator_hash() if digest is None else digest}


def read_recipe(value, current_hash=None):
    required = {"kind", "profile", "seed", "depth", "max_defs", "generator_hash"}
    if not isinstance(value, dict) or set(value) != required or value.get("kind") != RECIPE_KIND:
        raise ValueError("kernel replay requires a native seed recipe; legacy JSON Core artifacts are retired")
    if value["profile"] not in {"pr", "kernel", "nightly"}:
        raise ValueError("native recipe profile is invalid")
    if any(type(value[key]) is not int for key in ("seed", "depth", "max_defs")):
        raise ValueError("native recipe seed and bounds must be integers")
    if not (0 <= value["seed"] < 2**32 and 0 <= value["depth"] <= 8 and 1 <= value["max_defs"] <= 16):
        raise ValueError("native recipe seed or bounds are outside the supported range")
    if value["generator_hash"] != (generator_hash() if current_hash is None else current_hash):
        raise ValueError("cannot replay native recipe: generator hash differs; recover its exact generator sources")
    return CoreConfig([value["seed"]], value["profile"], value["depth"], value["max_defs"], 0)


def definition_count(seed, maximum):
    """Independent integer framing check; this does not evaluate Core terms."""
    def mix(value):
        value &= 0xFFFFFFFF
        value = ((value ^ (value >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
        value = ((value ^ (value >> 15)) * 0x846CA68B) & 0xFFFFFFFF
        return value ^ (value >> 16)
    return 1 + (mix(mix(seed) ^ (43 + 2257)) & 255) % maximum


def protocol_steps(seed, depth, maximum):
    count = definition_count(seed, maximum)
    prefix = f"ok smith seed={seed} "
    rows = [("domain=" + str(family), re.escape(prefix + "domain=" + str(family))) for family in range(18)]
    for name in range(400, 400 + count):
        rows.extend(((f"generated={name}", re.escape(prefix + f"generated={name} ") + r"family=(\d+) references=([0-9,]*)"),
                     (f"delta={name}", re.escape(prefix + f"delta={name}")),
                     (f"forms={name}", re.escape(f"forms seed={seed} selected=") + r"([0-7](?:,[0-7])*)?")))
    rows.extend((name, re.escape(prefix + name)) for name in OPERATIONS + RELATIONS + CONTROLS)
    rows.extend(("negative=" + name, re.escape(prefix + "negative=" + name)) for name in NEGATIVES)
    rows.append(("negative=rel-out-of-scope", re.escape(prefix + "negative=rel-out-of-scope target=") + r"(\d+)"))
    rows.extend((f"cold-delta={name}", re.escape(prefix + f"cold-delta={name}")) for name in range(400, 400 + count))
    rows.extend((("summary", re.escape(f"ok compiler-smith seed={seed} definitions={count} depth={depth} max-defs={maximum} domains=18 operations=27 relations=12 negatives=32 controls=3")),
                 ("complete", re.escape("ok compiler-smith complete"))))
    return rows


def inspect_result(result, seed, config):
    """Reject incomplete, duplicated, reordered or mismatched host output."""
    if result.status != "ok" or result.returncode not in (0, 1):
        category = result.classify()
        return {}, Failure("native-process", category if category in {"crash", "timeout", "memory"} else "oracle-unavailable",
                           f"{category} exit={result.returncode}: {result.stderr}")
    steps = protocol_steps(seed, config.depth, config.max_defs)
    lines = result.stdout.splitlines()
    coverage = {"definitions": definition_count(seed, config.max_defs), "families": [], "references": [], "forms": [], "rel_target": 0}
    if len(lines) > len(steps):
        return {}, Failure("native-protocol", "oracle-unavailable", "extra native result lines")
    for index, line in enumerate(lines):
        name, pattern = steps[index]
        match = re.fullmatch(pattern, line)
        if not match:
            return {}, Failure("native-protocol", "oracle-unavailable", f"unexpected result at {name}: {line}")
        if name.startswith("generated="):
            family, names = int(match[1]), match[2].split(",") if match[2] else []
            if family >= 18 or any(not item or not 400 <= int(item) < int(name.split("=")[1]) for item in names):
                return {}, Failure("native-protocol", "oracle-unavailable", "invalid generated family or forward reference")
            coverage["families"].append(family)
            coverage["references"].extend(int(item) for item in names)
        elif name.startswith("forms="):
            forms = [int(item) for item in match[1].split(",")] if match[1] else []
            if len(forms) < config.depth:
                return {}, Failure("native-protocol", "oracle-unavailable", "generated form depth was truncated")
            coverage["forms"].extend(forms)
        elif name == "negative=rel-out-of-scope":
            coverage["rel_target"] = int(match[1])
    if result.returncode == 0:
        if result.stderr or len(lines) != len(steps):
            return {}, Failure("native-protocol", "oracle-unavailable", "successful exit omitted results or emitted stderr")
        return coverage, None
    # The native driver stops at its first semantic failure. Its preceding
    # successes must be the exact prefix above, and the failing ID must be next.
    match = re.fullmatch(rf"not ok compiler-smith seed={seed} (.+)\n?", result.stderr)
    if not match or len(lines) >= len(steps):
        return {}, Failure("native-protocol", "oracle-unavailable", "nonzero exit lacks one exact native failure")
    next_name = steps[len(lines)][0]
    payload = match[1]
    early = "generator" if not lines and payload.startswith("generator ") else "environment" if not lines and payload.startswith("environment ") else None
    if early:
        name, detail = payload.split(" ", 1)
    elif next_name.startswith("generated="):
        failure = re.fullmatch(re.escape(next_name) + r" family=\d+ references=[0-9,]* (.+)", payload)
        if not failure:
            return {}, Failure("native-protocol", "oracle-unavailable", "generated failure ID disagrees with executed prefix")
        name, detail = next_name, failure[1]
    elif next_name == "negative=rel-out-of-scope" and payload.startswith("generator-rel "):
        name, detail = "generator-rel", payload.removeprefix("generator-rel ")
    elif next_name == "negative=rel-out-of-scope":
        failure = re.fullmatch(r"negative=rel-out-of-scope target=\d+ (.+)", payload)
        if not failure:
            return {}, Failure("native-protocol", "oracle-unavailable", "Rel failure ID disagrees with executed prefix")
        name, detail = next_name, failure[1]
    elif payload.startswith(next_name + " "):
        name, detail = next_name, payload[len(next_name) + 1:]
    elif next_name.startswith("cold-delta=") and payload.startswith("cold-environment "):
        name, detail = "cold-environment", payload.removeprefix("cold-environment ")
    else:
        return {}, Failure("native-protocol", "oracle-unavailable", "failure ID disagrees with executed result prefix")
    classification = "generator-error" if name in {"generator", "generator-rel"} else "property-violation"
    if name.startswith("negative="):
        classification = "wrong-accept" if " accepted input=" in detail else "wrong-class"
    return {}, Failure(name, classification, detail)


def shrink(config, seed, failure, evaluate):
    """Reduce only supported generation bounds, keeping exact failure identity."""
    current, remaining = config, config.shrink_budget
    for key, floor in (("max_defs", 1), ("depth", 0)):
        for value in range(floor, getattr(current, key)):
            if remaining <= 0:
                return current
            candidate = replace(current, **{key: value}, shrink_budget=0)
            remaining -= 1
            found = evaluate(candidate, seed)
            if found is not None and found.identity == failure.identity:
                current = candidate
                break
    return current


class CoreRunner:
    def __init__(self, config, report, program, *, timeout_s=20, log=print):
        self.config, self.report, self.program = config, report, program
        self.timeout_s, self.log = timeout_s, log
        self.attempt = 0

    def evaluate(self, config, seed):
        self.attempt += 1
        result = self.program.run(["--profile", config.profile, "--seed", str(seed), "--count", "1",
                                   "--depth", str(config.depth), "--max-defs", str(config.max_defs)],
                                  f"seed-{seed}-attempt-{self.attempt}", self.timeout_s)
        self.report.timing["kernel.process_s"] = self.report.timing.get("kernel.process_s", 0) + result.elapsed_s
        self.report.timing["kernel.peak_memory_mib"] = max(self.report.timing.get("kernel.peak_memory_mib", 0), result.peak_rss_mb)
        return inspect_result(result, seed, config)

    def run(self):
        summary = self.report.layer(LAYER)
        coverage = {"features": {}, "negative_kinds": {}, "properties": {}, "domains": {},
                    "forms": {}, "nonfirst_rel": 0, "earlier_references": 0, "definitions": 0}
        summary.coverage = coverage
        def add(group, name, count=1):
            coverage[group][name] = coverage[group].get(name, 0) + count
        for ordinal, seed in enumerate(self.config.seeds):
            original = recipe(self.config, seed, self.report.generator_hash)
            # Validate before executing even for direct API callers.
            read_recipe(original, self.report.generator_hash)
            summary.cases += 1
            laws, failure = self.evaluate(self.config, seed)
            if failure is not None:
                minimum = self.config
                original_failure = failure
                attempts = {}
                def evaluate(candidate, selected):
                    found = self.evaluate(candidate, selected)[1]
                    attempts[(candidate.depth, candidate.max_defs)] = found
                    return found
                if self.config.shrink_budget and failure.classification not in {"oracle-unavailable", "crash", "timeout", "memory", "generator-error"}:
                    minimum = shrink(self.config, seed, failure, evaluate)
                    failure = attempts.get((minimum.depth, minimum.max_defs)) or failure
                saved = recipe(minimum, seed, self.report.generator_hash)
                path = self.program.work / f"seed-{seed}-recipe.json"
                path.write_text(json.dumps({"original": original, "minimal": saved,
                                            "failure": {"prop": original_failure.prop, "classification": original_failure.classification,
                                                        "detail": original_failure.detail}}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
                finding = Finding(LAYER, failure.prop, failure.classification, seed, self.config.profile,
                                  self.report.generator_hash, f"core-{seed}", "native-kernel", failure.expected,
                                  failure.detail, saved, "", self.config.depth * self.config.max_defs,
                                  minimum.depth * minimum.max_defs, notes=["Original recipe: " + json.dumps(original, sort_keys=True)])
                finding_path = self.program.work / f"finding-{finding.finding_id}.json"
                from ourosmith import ROOT
                finding.replay = f"{self.config.replay_prefix} replay --finding {finding_path.relative_to(ROOT).as_posix()}"
                finding_path.write_text(json.dumps(finding.to_json(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
                self.report.add(finding)
                continue
            count = laws["definitions"]
            summary.positive_checks += 48 + count
            summary.negative_checks += 32
            summary.property_checks += 92 + 3 * count
            coverage["definitions"] += count
            for family in range(18):
                add("domains", str(family))
                add("features", "domain:" + str(family))
            for name in OPERATIONS + RELATIONS + CONTROLS:
                add("properties", name)
            for name in NEGATIVES + ["rel-out-of-scope"]:
                add("negative_kinds", name)
            for form in laws["forms"]:
                add("forms", FORMS[form])
                add("features", "form:" + FORMS[form])
            if laws["rel_target"] > 0:
                coverage["nonfirst_rel"] += 1
                add("features", "mutation:nonfirst-rel")
            if laws["references"]:
                coverage["earlier_references"] += len(laws["references"])
                add("features", "definition:earlier-reference")
            for name in ("generated-independent", "delta-independent", "cold-independent"):
                add("properties", name, count)
            if ordinal == 0 or (ordinal + 1) % 10 == 0 or ordinal + 1 == len(self.config.seeds):
                self.log(f"OURO_SMITH: kernel {ordinal + 1}/{len(self.config.seeds)} seed={seed}")
