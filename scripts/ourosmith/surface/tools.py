"""Generated tool contracts: no fixed declaration offsets or compiler oracle."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

from ourosmith import ROOT
from ourosmith.host import environment, job_count, shell
from ourosmith.surface.gen import PRELUDE


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def documentation(run, directory, saved=None):
    from ourosmith.surface.doc_contract import program

    if saved is not None and "source" in saved:
        text, expected, signature, prose = (saved[key] for key in ("source", "expected_markdown", "signature", "prose"))
    else:
        imported = os.path.relpath(ROOT / "std/prelude.ouro", directory).replace("\\", "/")
        text, expected, signature, prose = program(run.seed, imported)
    run.input = {"recipe": "documentation", "seed": run.seed, "source": text,
                 "expected_markdown": expected, "signature": signature, "prose": prose}
    path = write(directory / "documented.ouro", text)
    out = directory / "docs"
    # Repeated replay must prove fresh generation, even in the same work dir.
    for page in out.glob("*.md"):
        page.unlink()
    result = run.command([run.tool("ouro-doc"), "--out", out, path], directory, "doc-generate")
    run.require(result.ok, "doc-generate", "exit 0", run.output(result))
    pages = [page for page in out.glob("*.md") if page.name != "README.md"]
    body = "".join(page.read_text(encoding="utf-8") for page in pages)
    run.require(signature in body and prose in body,
                "doc-signature-comment", signature, body)
    expected = "# " + path.as_posix() + "\n\n" + expected
    run.require(len(pages) == 1 and (out / "README.md").is_file() and body == expected,
                "doc-layout", expected, body)
    checked = run.command([run.tool("ouro-doc"), "--check", "--out", out, path], directory, "doc-check")
    run.require(checked.ok, "doc-check", "exit 0", run.output(checked))
    # The independent oracle requires a changed source signature to invalidate
    # the previously generated output, even when names stay the same.
    write(path, text + f"\naxiom added{run.seed} : Type;\n")
    changed = run.command([run.tool("ouro-doc"), "--check", "--out", out, path], directory, "doc-drift")
    run.require(changed.returncode == 1, "doc-drift", "exit 1", run.output(changed))


def frame(message):
    body = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
    return f"Content-Length: {len(body.encode())}\r\n\r\n{body}"


def responses(stream):
    output = []
    while stream:
        header = re.match(r"Content-Length: ([0-9]+)\r?\n\r?\n", stream)
        if not header:
            raise ValueError("invalid LSP frame header")
        # Requests and generated names are ASCII. Non-ASCII response payloads
        # still use the protocol's byte length.
        data = stream[header.end():].encode("utf-8")
        length = int(header[1])
        if length > len(data):
            raise ValueError("truncated LSP frame")
        output.append(json.loads(data[:length]))
        stream = data[length:].decode("utf-8")
    return output


def language_server(run, directory):
    name = f"symbol{run.seed}"
    source = PRELUDE + f"-- Hover contract for {name}.\ndef {name} (n : Nat) : Nat := S n;\ndef usage : Nat := {name} Z;\n"
    path = write(directory / "symbols.ouro", source)
    uri = path.as_uri()
    lines = source.splitlines()
    definition = next(i for i, line in enumerate(lines) if line.startswith(f"def {name} "))
    usage = len(lines) - 1
    params = {"textDocument": {"uri": uri}, "position": {"line": usage, "character": lines[usage].index(name) + 1}}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootUri": directory.as_uri(), "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "languageId": "ouro", "version": 1, "text": source}}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": params},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition", "params": params},
        {"jsonrpc": "2.0", "id": 4, "method": "textDocument/documentSymbol", "params": {"textDocument": {"uri": uri}}},
        {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    result = run.command([run.tool("ouro-lsp")], directory, "lsp-session", stdin="".join(map(frame, requests)))
    run.require(result.ok and not result.stderr, "lsp-session", "exit 0, no stderr", run.output(result))
    try:
        messages = responses(result.stdout)
    except (ValueError, UnicodeError) as exc:
        run.require(False, "lsp-framing", "valid framed JSON", str(exc))
        return
    replies = {message["id"]: message for message in messages if "id" in message}
    run.require(set(replies) == {1, 2, 3, 4, 5}, "lsp-reply-ids", [1, 2, 3, 4, 5], sorted(replies))
    hover = json.dumps(replies[2])
    run.require(f"def {name} (n : Nat) : Nat" in hover and f"Hover contract for {name}" in hover,
                "lsp-hover", name, replies[2])
    definition_result = replies[3].get("result")
    run.require(isinstance(definition_result, dict) and definition_result.get("uri") == uri
                and definition_result.get("range", {}).get("start", {}).get("line") == definition,
                "lsp-definition", {"uri": uri, "line": definition}, replies[3])
    run.require(f'"name": "{name}"' in json.dumps(replies[4]), "lsp-symbol", name, replies[4])
    run.require(replies[5].get("result", "missing") is None, "lsp-shutdown", None, replies[5])


def fixer(run, directory):
    # An unused pure let is dead by construction; the result is known before
    # running the fixer, whose preservation is also checked via native output.
    original = PRELUDE + f"def result : Nat := let unused : Nat := {run.seed % 5} in S Z;\n"
    path = write(directory / "fixable.ouro", original)
    run.accepts(path)
    checked = run.command([run.tool("ouro-fix"), "--check", path], directory, "fix-check-dirty")
    run.require(checked.returncode == 1, "fix-check-dirty", "exit 1", run.output(checked))
    fixed = run.command([run.tool("ouro-fix"), path], directory, "fix-output")
    run.require(fixed.ok and "let unused" not in fixed.stdout, "fix-dead-let", "unused pure let removed", run.output(fixed))
    write(path, fixed.stdout)
    run.accepts(path)
    again = run.command([run.tool("ouro-fix"), path], directory, "fix-idempotent")
    run.require(again.ok and again.stdout == fixed.stdout, "fix-idempotent", fixed.stdout, run.output(again))
    lint = run.command([run.tool("ouro-lint"), path], directory, "fix-lint-clean")
    run.require(lint.ok and not lint.stdout.strip(), "fix-lint-clean", "no lint diagnostics", run.output(lint))
    result = run.native(path)
    run.require(result.ok and result.stdout == "S Z : Nat\n", "fix-runtime-preservation", "S Z : Nat\n", run.output(result))


def import_modules(run, directory):
    dep = write(directory / "numbers.ouro", PRELUDE + f"def value : Nat := {run.seed % 5};\n")
    path = write(directory / "imports.ouro", 'import "numbers.ouro" as N;\ndef result : N.Nat := N.S N.value;\n')
    collected = run.command([run.tool("ouro-collect"), path], directory, "import-collect")
    got = [line.replace("\\", "/") for line in collected.stdout.splitlines() if line.strip()]
    expected = [dep.as_posix(), path.as_posix()]
    run.require(collected.ok and got == expected, "import-dependency-order", expected, run.output(collected))
    dotted = run.command([run.tool("ouro-collect"), directory.as_posix() + "/./imports.ouro"], directory, "import-collect-dot")
    run.require(dotted.ok and dotted.stdout == collected.stdout, "import-dependency-order", expected, run.output(dotted))
    first = run.accepts(path, units=[dep, path], env=environment(jobs=1))
    second = run.accepts(path, units=[dep, path], env=environment(jobs=job_count()))
    run.require(first == second, "import-jobs-equality", first, second)
    # Exercise local opens against the same known dependency, not merely an
    # unchanged second check of the original source.
    opened = write(directory / "opened.ouro", 'import "numbers.ouro" as N;\ndef result : Nat := open N in S value;\n')
    third = run.accepts(opened, units=[dep, opened])
    run.require(first == third, "import-alias-open-equality", first, third)


def module_suffixes(run, directory):
    path = write(directory / "module.ouro", "inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\ndef result : Nat := Z;\n")
    suffixes = ["", f"_valid{run.seed}", "_", "bad", "_bad suffix", "_bad/*x*/", "_bad#x", '_bad"x', "_bad;x", "_bad\nx"]
    for suffix in suffixes:
        result = run.command([run.compiler, path, "999999", "--module", suffix], directory, "module-suffix")
        good = suffix == "" or re.fullmatch(r"_[A-Za-z0-9_]+", suffix) is not None
        if good:
            run.require(result.ok and f"int ouro_export_count{suffix}(void)" in result.stdout,
                        "module-suffix-valid", "exact exported C symbol", run.output(result))
        else:
            run.require(result.returncode == 2 and not result.stdout and "--module must be empty or match _[A-Za-z0-9_]+" in result.stderr,
                        "module-suffix-reject", "exit 2, empty stdout, suffix diagnostic", run.output(result))


def module_cache(run, directory):
    from cache_parity_suite import comparable_module_report

    dep = write(directory / "leaf.ouro", PRELUDE + f"def cached : Nat := {run.seed % 5};\n")
    path = write(directory / "root.ouro", 'import "leaf.ouro";\ndef result : Nat := S cached;\n')
    # Each replay needs a genuinely cold cache, including repeated --out.
    # A short private directory keeps cache filenames within Windows limits.
    cache = tempfile.mkdtemp(prefix="mc-", dir=run.work)
    comparable = []
    for label, enabled, jobs in (("cold", True, 1), ("warm", True, job_count()), ("disabled", False, 1)):
        report_path = directory / f"{label}.json"
        result = run.command([sys.executable, run.module_cache, "--root", path,
                              "--work", directory / label, "--cache-root", cache, "--report", report_path,
                              "--cache" if enabled else "--no-cache"], directory, "module-cache-" + label,
                             env=environment(jobs=jobs))
        run.require(result.ok and report_path.is_file(), "module-cache-" + label, "exit 0 and report", run.output(result))
        data = json.loads(report_path.read_text(encoding="utf-8"))
        summary = data["summary"]
        run.require(summary["modules"] == 2, "module-cache-graph", 2, summary["modules"])
        if enabled:
            key = "direct_hits" if label == "warm" else "direct_misses"
            run.require(summary[key] == 2, "module-cache-" + key, 2, summary[key])
        comparable.append(comparable_module_report(report_path))
    run.require(comparable[0] == comparable[1] == comparable[2], "module-cache-parity", comparable[0], comparable[1:])
    before = run.accepts(path, units=[dep, path])
    write(dep, PRELUDE + f"def cached : Nat := {run.seed % 5 + 1};\n")
    report_path = directory / "changed.json"
    result = run.command([sys.executable, run.module_cache, "--root", path,
                          "--work", directory / "warm", "--cache-root", cache, "--report", report_path], directory, "module-cache-invalidate")
    run.require(result.ok, "module-cache-invalidate", "exit 0", run.output(result))
    summary = json.loads(report_path.read_text(encoding="utf-8"))["summary"]
    run.require(summary["direct_misses"] == 1 and summary["closure_misses"] == 2,
                "module-cache-dependency-invalidation", {"direct": 1, "closure": 2}, summary)
    run.require(run.accepts(path, units=[dep, path]) != before, "module-cache-changed-artifact", "changed declaration artifact", "unchanged artifact")


def user_test_runner(run, directory):
    count = 2 + run.seed % 4
    files = []
    for failing in (False, True):
        name = "failure" if failing else "success"
        rows = [f'test_ok "case{i}"' for i in range(count)]
        expected = f"seed{run.seed}\n" + "".join(f"ok case{i}\n" for i in range(count))
        if failing:
            rows.append('test_fail "broken" "intentional"')
            expected += "FAIL broken intentional\n"
        dependency = os.path.relpath(ROOT / "std/test.ouro", directory).replace("\\", "/")
        source = (f'import "{dependency}";\n-- @entry main\ndef main : IO Unit :=\n'
                  f'  do let! label := io_pure String "seed{run.seed}";\n'
                  '     println label;\n     test_run ([' + ", ".join(rows) + "] : List Test)\n")
        path = write(directory / f"{name}_test.ouro", source)
        write(path.with_suffix(".golden"), expected)
        exe = directory / (name + ".exe")
        built = run.command([shell(), ROOT / "scripts/build_tool.sh", path, exe], ROOT, "test-program-build",
                            env=environment(build=True), timeout=120)
        run.require(built.ok, "test-program-build", "exit 0", run.output(built))
        actual = run.command([exe], directory, "test-program-run")
        run.require(actual.returncode == int(failing) and actual.stdout == expected,
                    "test-known-counts", {"exit_code": int(failing), "stdout": expected}, run.output(actual))
        files.append(path)
    env = environment(build=True)
    env["OURO_TEST_OUT"] = (directory / "runner-bin").as_posix()
    for name, inputs, rc, fragment in (("pass", files[:1], 0, "test: ok"), ("fail", files, 1, "test: failed")):
        result = run.command([run.tool("ouro-test"), *inputs], directory, "test-runner-" + name, env=env, timeout=180)
        run.require(result.returncode == rc and fragment in result.stdout + result.stderr,
                    "test-runner-" + name, {"exit_code": rc, "message": fragment}, run.output(result))
    discovered = run.command([shell(), ROOT / "scripts/ouro1.sh", "test"], directory,
                             "test-runner-discovery", env=environment(build=True), timeout=180)
    expected_failure = ("process failed: _build/ouro_test/failure_test exit=1 stderr=\n"
                        "FAIL run ./failure_test.ouro\ntest: failed\n")
    run.require(discovered.returncode == 1 and discovered.stdout == "ok run ./success_test.ouro\n"
                and discovered.stderr == expected_failure,
                "test-runner-discovery", "discover and run the passing and intentionally failing local tests", run.output(discovered))
    write(files[0].with_suffix(".golden"), "deliberately wrong golden\n")
    result = run.command([run.tool("ouro-test"), files[0]], directory, "test-runner-golden", env=env, timeout=120)
    run.require(result.returncode == 1 and "FAIL golden" in result.stderr, "test-runner-golden", "exit 1, golden mismatch", run.output(result))


def selftest_missing_golden(run, directory):
    # A readable input and absent golden reach each selftest's checked read
    # failure branch. Exiting must prevent the typed continuation returning.
    for tool, name, suffix, option in (("fmt", "clean", ".in", "--selftest-worker=clean"),
                                        ("fix", "read_failure", ".in", "--selftest"),
                                        ("doc", "sample", ".ouro", "--selftest")):
        work = directory / tool
        fixtures = work / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        write(fixtures / (name + suffix), "def value : Type := Type;\n")
        # Doc output names encode the input path; keep the fixture relative so
        # a long work directory cannot hit Windows MAX_PATH before the golden.
        result = run.command([run.tool("ouro-" + tool), option, "--out=result", "--fixtures=fixtures"], work, "selftest-missing-golden-" + tool)
        output = result.stdout + result.stderr
        run.require(result.returncode == 1 and name + ".golden" in output and "path not found:" in output
                    and f"{tool.upper()}_SUITE: FAIL" in output and "SUITE: PASS" not in output,
                    "selftest-read-failure-" + tool, "exit 1 with missing-golden diagnostic", run.output(result))


def stdlib_strings(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "strings")


def stdlib_paths(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "paths")


def stdlib_data(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "data")


def stdlib_crypto(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "crypto")


def stdlib_protocols(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "protocols")


def stdlib_tables(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "tables")


def stdlib_helpers(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "helpers")


def stdlib_workflow(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "workflow")


def stdlib_application(run, directory):
    from ourosmith.surface.library import run_family

    run_family(run, directory, "application")


def lint_contracts(run, directory):
    from ourosmith.surface.lint_contracts import run_checks

    run_checks(run, directory)


def analyzer_lines(run, directory):
    from ourosmith.surface.analyzer_lines import run_checks

    run_checks(run, directory)


def analyzer_ast(run, directory):
    from ourosmith.surface.analyzer import run_checks

    run_checks(run, directory)


def runtime_io(run, directory):
    from ourosmith.surface.io import run_checks

    run_checks(run, directory)


def text_tools(run, directory):
    from ourosmith.surface.text_contracts import run_checks

    run_checks(run, directory)


def compiler_parity(run, directory):
    from ourosmith.surface.parity import run_checks

    run_checks(run, directory)


def backend_depth(run, directory):
    from ourosmith.surface.backend import run_checks

    run_checks(run, directory)


def manifest_contract(run, directory):
    from ourosmith.surface.manifest import run_checks

    run_checks(run, directory)


def parser_contract(run, directory):
    from ourosmith.surface.parser import run_checks

    run_checks(run, directory)


PROPERTIES = (documentation, language_server, fixer, import_modules, module_suffixes, module_cache,
              user_test_runner, selftest_missing_golden, stdlib_strings, stdlib_paths, stdlib_data, stdlib_crypto,
              stdlib_protocols, stdlib_tables, stdlib_helpers, stdlib_workflow, stdlib_application, analyzer_ast, analyzer_lines,
              runtime_io, text_tools, lint_contracts, compiler_parity, backend_depth, manifest_contract, parser_contract)


def run_tools(run, only=None, saved=None):
    from ourosmith.surface.run import StepFailure

    if saved is not None and set(saved) <= {"recipe", "seed"}:
        saved = None
    for test in PROPERTIES:
        if only is not None and test.__name__ != only:
            continue
        run.case_id = f"surface-{run.seed}-{test.__name__}"
        run.input = {"recipe": test.__name__, "seed": run.seed}
        directory = run.work / "cases" / run.case_id
        directory.mkdir(parents=True, exist_ok=True)
        try:
            if saved is not None and test.__name__ == "documentation":
                documentation(run, directory, saved=saved)
            elif saved is not None and test.__name__ == "text_tools":
                from ourosmith.surface.text_contracts import run_checks

                run_checks(run, directory, saved=saved)
            elif saved is not None and test.__name__.startswith("stdlib_"):
                from ourosmith.surface.library import run_family

                run_family(run, directory, test.__name__[7:], saved=saved)
            elif saved is not None and test.__name__ == "analyzer_ast":
                from ourosmith.surface.analyzer import run_checks

                run_checks(run, directory, saved=saved)
            elif saved is not None and test.__name__ == "analyzer_lines":
                from ourosmith.surface.analyzer_lines import run_checks

                run_checks(run, directory, saved=saved)
            elif saved is not None and test.__name__ == "lint_contracts":
                from ourosmith.surface.lint_contracts import run_checks

                run_checks(run, directory, saved=saved)
            elif saved is not None and test.__name__ == "runtime_io":
                from ourosmith.surface.io import run_checks

                run_checks(run, directory, saved=saved)
            elif saved is not None and test.__name__ in {"compiler_parity", "backend_depth", "manifest_contract", "parser_contract"}:
                from ourosmith.surface import backend, manifest, parity, parser

                module = {"compiler_parity": parity, "backend_depth": backend, "manifest_contract": manifest, "parser_contract": parser}[test.__name__]
                module.run_checks(run, directory, saved=saved)
            else:
                test(run, directory)
        except StepFailure as failure:
            run.record(failure)
