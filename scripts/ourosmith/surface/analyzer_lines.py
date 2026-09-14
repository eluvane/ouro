"""Independent byte-level contract for the analyzer source-line scanner."""
from __future__ import annotations

import json
import os

from ourosmith import ROOT
from ourosmith.host import BUILD_TIMEOUT_S


def program(seed):
    texts = ['', '\n', '\n\n', f'line{seed}', f'line{seed}\n', f'line{seed}\n\n',
             '\r\n', 'first\r\nsecond\n', 'first\rsecond', 'x' * (257 + seed % 19)]
    expected = []
    for text in texts:
        lines = text.split('\n')
        if lines[-1] == '':
            lines.pop()
        expected.append(''.join('[' + ''.join(str(ord(c)) + ',' for c in line) + ']' for line in lines))
    definitions = '''def render_codes : List Nat -> String :=
fix render_codes (codes : List Nat) : String := match codes with
| Nil => ""
| Cons code rest => prim_string_concat (prim_string_of_nat code)
    (prim_string_concat "," (render_codes rest)) end;
def render_lines : List (List Nat) -> String :=
fix render_lines (lines : List (List Nat)) : String := match lines with
| Nil => ""
| Cons line rest => prim_string_concat "[" (prim_string_concat (render_codes line)
    (prim_string_concat "]" (render_lines rest))) end;
'''
    actions = '\n'.join('  println (render_lines (unit_split_lines (prim_string_to_char_codes ' + json.dumps(text) + ')));' for text in texts)
    source = definitions + '\n-- @entry main\ndef main : IO Unit :=\n do\n' + actions + '\n  exit 0\n'
    return source, '\n'.join(expected) + '\n'


def run_checks(run, directory, saved=None):
    from frontend_regen import collect_units

    source, expected = (saved["source"], saved["expected_stdout"]) if saved is not None and "source" in saved else program(run.seed)
    run.input = {"recipe": "analyzer_lines", "seed": run.seed, "source": source, "expected_stdout": expected}
    imports = "".join("import " + json.dumps(os.path.relpath(ROOT / module, directory).replace("\\", "/")) + ";\n"
                      for module in ("std/io.ouro", "tools/analyze/unit.ouro"))
    path = directory / "main.ouro"
    path.write_text(imports + source, encoding="utf-8", newline="\n")
    units = collect_units(path.as_posix())
    # This integration input imports the analyzer's full frontend graph.
    # Keep its compile budget separate from the generated program's deadline.
    compile_timeout = BUILD_TIMEOUT_S
    run.accepts(path, artifact=False, units=units, timeout=compile_timeout)
    actual = run.native(path, units=units, io=True, compile_timeout=compile_timeout)
    run.require(actual.ok and actual.stdout == expected and not actual.stderr,
                "analyzer-lines", expected, run.output(actual))
    run.count("features", "analyzer:line-splitting")
