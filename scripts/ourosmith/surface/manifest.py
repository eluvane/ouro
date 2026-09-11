"""Generated native manifest contracts, including false-success protection."""
import json
from ourosmith.surface.gen import PRELUDE


def inputs(seed):
    return {"good.ouro": PRELUDE + f"def value{seed} : Nat := {seed % 5};\n",
            "bad.ouro": PRELUDE + f"def value{seed} : Nat := True;\n"}


def run_checks(run, directory, saved=None):
    sources = saved["sources"] if saved is not None else inputs(run.seed)
    run.input = {"recipe": "manifest_contract", "sources": sources}
    for name, text in sources.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")
    def execute(name, text, code, diagnostic, *, env=None):
        manifest = directory / (name + ".tsv")
        manifest.write_text(text, encoding="utf-8", newline="\n")
        out = directory / name
        result = run.command([run.tool("ouro-test"), "--manifest=" + manifest.as_posix(),
                              "--root=" + directory.as_posix(), "--prefix=SMITH.", "--out=" + out.as_posix(),
                              "--suite-label=SMITH_MANIFEST"], directory, "manifest-" + name, env=env)
        run.require(result.returncode == code and diagnostic in result.stdout + result.stderr,
                    "manifest-" + name, {"exit_code": code, "diagnostic": diagnostic}, run.output(result))
        if code < 2:
            data = json.loads((out / "manifest-report.json").read_text(encoding="utf-8"))
            run.require(data["pass"] is (code == 0) and data["failures"] == code and data["rows"] == 1,
                        "manifest-report-" + name, {"pass": code == 0, "failures": code, "rows": 1}, data)

    good = "SMITH.good\tgood.ouro\tcheck\tpass\t0\tCHECK_OK\n"
    bad = "SMITH.bad\tbad.ouro\tcheck\tfail\t0\tCErr code=41\n"
    execute("accept", good, 0, "SMITH_MANIFEST: PASS rows=1")
    execute("reject", bad, 0, "SMITH_MANIFEST: PASS rows=1")
    execute("invert-accept", good.replace("\tpass\t", "\tfail\t"), 1, "expected fail")
    execute("invert-reject", bad.replace("\tfail\t", "\tpass\t"), 1, "expected pass")
    execute("diagnostic", bad.replace("CErr code=41", "CErr code=43"), 1, "missing CErr code=43")
    execute("missing", bad.replace("bad.ouro", "missing.ouro"), 1, "missing file")
    for name, text, diagnostic in (
        ("duplicate", good + good, "duplicate id:"),
        ("columns", good.rstrip() + "\textra\n", "expected exactly six tab-separated columns"),
        ("traversal", good.replace("good.ouro", "../good.ouro"), "unsafe or empty path"),
        ("unsupported", good.replace("\tcheck\t", "\tlint\t"), "unsupported selected tool"),
        ("empty", good.replace("SMITH.", "OTHER."), "no rows selected"),
        ("number", good.replace("\t0\t", "\t-1\t"), "min_issues must be a natural number"),
    ):
        execute(name, text, 2, diagnostic)
    for code, text in ((139, "CErr code=41"), (2, "CErr code=41"), (0, "no acceptance marker")):
        script = directory / f"status-{code}.sh"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{text}'\nexit {code}\n", encoding="utf-8", newline="\n")
        execute(f"status-{code}", good if code == 0 else bad, 1, "SMITH_MANIFEST: FAIL",
                env={**run.env, "OURO_TEST_CHECK": script.as_posix()})
    run.count("features", "manifest:integrity")
