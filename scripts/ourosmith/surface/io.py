"""Generated filesystem and process contracts checked against Python state."""
from __future__ import annotations

import json
import os
import time

from ourosmith import ROOT
from ourosmith.host import BUILD_TIMEOUT_S
from ourosmith.surface.library import quote, string_list

FEATURES = ("filesystem", "filesystem-errors", "walk", "walk-limit", "temporary-files",
            "process-argv", "process-status", "environment", "stdin", "clock", "delay-action")

HELPERS = """
def unit_value (r : Either FsError Unit) : String :=
  match r with | Left e => fs_error_code e | Right _ => "ok" end;
def text_value (r : Either FsError String) : String :=
  match r with | Left e => fs_error_code e | Right value => value end;
def names_value (r : Either FsError (List String)) : String :=
  match r with | Left e => fs_error_code e
  | Right names => str_join "|" (str_sort_uniq names) end;
def walk_value (r : FsWalkResult) : String :=
  match r with
  | FsWalkComplete names => str_join "|" (str_sort_uniq names)
  | FsWalkTruncated _ => "truncated"
  | FsWalkUnreadable _ => "unreadable"
  | FsWalkUnsafe _ => "unsafe"
  end;
def checked_process_value (r : Either ProcessError ProcResult) : String :=
  match r with
  | Left e => str_concat (process_error_code e) (show_nat (process_error_status e))
  | Right _ => "ok"
  end;
def argv_value (args : List String) : String :=
  match args with | Nil => "missing argv0" | Cons _ rest => str_join "|" rest end;
"""

CHILD = r"""#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
int main(int argc, char **argv) {
    if (argc < 2) return 91;
#ifdef _WIN32
    if (_setmode(_fileno(stdout), _O_BINARY) == -1 ||
        _setmode(_fileno(stderr), _O_BINARY) == -1) return 92;
#endif
    for (int i = 2; i < argc; ++i) { fputs(argv[i], stdout); putchar('\n'); }
    fputs("helper err\n", stderr);
    return atoi(argv[1]);
}
"""


def program(seed):
    lines, expected = [], {}
    body = f"content-{seed}"

    def output(name, expression, value):
        lines.append(f'println (str_concat {quote(name + "=")} ({expression}));')
        expected[name] = value

    def observe(name, action, render, value):
        lines.append(f"let! {name} := {action};")
        output(name, f"{render} {name}", value)

    observe("clean", 'fsx_remove_tree_checked "data"', "unit_value", "ok")
    observe("mkdir", 'fs_mkdir_p_checked "data"', "unit_value", "ok")
    observe("write", f'fs_write_checked "data/a.txt" {quote(body)}', "unit_value", "ok")
    observe("append", 'fs_append_checked "data/a.txt" "-more"', "unit_value", "ok")
    observe("read", 'fs_read_checked "data/a.txt"', "text_value", body + "-more")
    observe("copy", 'fs_copy_checked "data/a.txt" "data/b.txt"', "unit_value", "ok")
    observe("copied", 'fs_read_checked "data/b.txt"', "text_value", body + "-more")
    observe("empty", 'fs_write_checked "data/empty.txt" ""', "unit_value", "ok")
    observe("emptyread", 'fs_read_checked "data/empty.txt"', "text_value", "")
    for name, action, expected_value in (
        ("fileexists", 'fs_file_exists "data/a.txt"', "true"),
        ("direxists", 'fs_dir_exists "data"', "true"),
        ("fileisdir", 'fs_dir_exists "data/a.txt"', "false"),
        ("dirisfile", 'fs_file_exists "data"', "false"),
    ):
        observe(name, action, "show_bool", expected_value)
    for name, action, renderer, value in (
        ("missing", 'fs_read_checked "data/missing"', "text_value", "not_found"),
        ("directory", 'fs_read_checked "data"', "text_value", "not_file"),
        ("emptypath", 'fs_read_checked ""', "text_value", "empty_path"),
        ("badwrite", 'fs_write_checked "data" "bad"', "unit_value", "not_file"),
        ("badappend", 'fs_append_checked "data/missing" "bad"', "unit_value", "not_found"),
        ("badcopy", 'fs_copy_checked "data/missing" "data/absent"', "unit_value", "not_found"),
        ("badlist", 'fs_list_checked "data/a.txt"', "names_value", "not_directory"),
        ("listed", 'fs_list_checked "data"', "names_value", "a.txt|b.txt|empty.txt"),
        ("walked", 'fs_walk_checked "data"', "walk_value", "data/a.txt|data/b.txt|data/empty.txt"),
        ("walkmissing", 'fs_walk_checked "data/missing"', "walk_value", "unreadable"),
    ):
        observe(name, action, renderer, value)
    lines.append('let! realroot := prim_fs_realpath "data";')
    observe("limited", 'fs_walk_checked_go 1 realroot (["data"] : List String) (Nil String)', "walk_value", "truncated")
    output("limitmessage", 'show_bool (str_contains (fs_walk_message limited) "walk limit reached")', "true")
    lines.extend(['let! tmpone := prim_fs_temp_file_in "data";', 'let! tmptwo := prim_fs_temp_file_in "data";',
                  'let! existsone := fs_exists tmpone;', 'let! existstwo := fs_exists tmptwo;'])
    output("unique", "show_bool (andb (notb (str_null tmpone)) (andb (notb (str_eq tmpone tmptwo)) (andb existsone existstwo)))", "true")
    observe("removeone", "fsx_remove_if_exists tmpone", "unit_value", "ok")
    observe("removetwo", "fsx_remove_if_exists tmptwo", "unit_value", "ok")
    observe("leaf", 'fs_write_checked "data/tree/nested/leaf.txt" "leaf"', "unit_value", "ok")
    observe("copytree", 'fsx_copy_tree_checked "data/tree" "data/copied"', "unit_value", "ok")
    observe("removetree", 'fsx_remove_tree_checked "data/tree"', "unit_value", "ok")
    observe("removemissingtree", 'fsx_remove_tree_checked "data/tree"', "unit_value", "ok")
    observe("treegone", 'fs_exists "data/tree"', "show_bool", "false")
    observe("envvalue", 'env_or "OURO_SMITH_VALUE" "missing"', "", f"env-{seed}")
    observe("envmissing", 'env_or "OURO_SMITH_ABSENT" "fallback"', "", "fallback")
    observe("processenvmissing", 'process_env_or "OURO_SMITH_ABSENT" "fallback"', "", "fallback")
    lines.append(f'delay_then Unit Z (println {quote("delayed=action-" + str(seed))});')
    expected["delayed"] = f"action-{seed}"
    observe("args", "argv", "argv_value", "alpha|space arg|")
    observe("line", "readLine", "", f"line-{seed}")
    observe("bytes", "prim_stdin_read_bytes 3", "", "xyz")
    child_args = ["", f"arg-{seed}", "with spaces", "'quoted'", '"double"', ";$`&<>|()"]
    for code in (0, 7):
        args = string_list([str(code), *child_args])
        lines.append(f'let! child{code} := process_run_spec (command_spec "./process helper.exe" {args});')
        output(f"code{code}", f"show_nat (proc_code child{code})", str(code))
        output(f"out{code}", f"json_print (JStr (proc_stdout child{code}))", json.dumps("\n".join(child_args) + "\n"))
        output(f"err{code}", f"json_print (JStr (proc_stderr child{code}))", json.dumps("helper err\n"))
        observe(f"checked{code}", f'process_run_spec_checked (command_spec "./process helper.exe" {args})',
                "checked_process_value", "ok" if code == 0 else "process_failed7")
    observe("clock", "now", "", None)
    lines += ["flush;", "exit 0"]
    source = HELPERS + "\n-- @entry main\ndef main : IO Unit :=\n  do " + "\n     ".join(lines) + "\n"
    files = {"a.txt": (body + "-more").encode(), "b.txt": (body + "-more").encode(),
             "empty.txt": b"", "copied/nested/leaf.txt": b"leaf"}
    return source, expected, files


def run_checks(run, directory, saved=None):
    from frontend_regen import collect_units

    if saved is not None and "source" in saved:
        source, expected = saved["source"], saved["expected_values"]
        expected_files = {name: bytes.fromhex(data) for name, data in saved["expected_files"].items()}
        child_source, env_value, stdin = saved["child_source"], saved["env_value"], saved["stdin"]
        arguments = saved["arguments"]
    else:
        source, expected, expected_files = program(run.seed)
        child_source, env_value, stdin = CHILD, f"env-{run.seed}", f"line-{run.seed}\nxyz"
        arguments = ["alpha", "space arg", ""]
    run.input = {"recipe": "runtime_io", "source": source, "expected_values": expected,
                 "expected_files": {name: data.hex() for name, data in expected_files.items()},
                 "child_source": child_source, "env_value": env_value, "stdin": stdin, "arguments": arguments}
    imports = "".join(f'import {quote(os.path.relpath(ROOT / "std" / (name + ".ouro"), directory).replace(chr(92), "/"))};\n'
                      for name in ("workspace", "fs_walk", "processx", "json", "async"))
    path = directory / "main.ouro"
    path.write_text(imports + source, encoding="utf-8", newline="\n")
    child = directory / "child.c"
    child.write_text(child_source, encoding="utf-8", newline="\n")
    run.require(run.cc is not None, "io-helper-compile", "C compiler", run.cc)
    built = run.command([run.cc, "-O1", "-std=c99", child, "-o", directory / "process helper.exe"], directory, "io-helper-compile")
    run.require(built.ok, "io-helper-compile", "exit 0", run.output(built))
    units = collect_units(path.as_posix())
    compile_timeout = BUILD_TIMEOUT_S
    run.accepts(path, artifact=False, units=units, timeout=compile_timeout)
    env = {**run.env, "OURO_SMITH_VALUE": env_value}
    env.pop("OURO_SMITH_ABSENT", None)
    start = time.time_ns() // 1_000_000
    actual = run.native(path, units=units, io=True, env=env,
                        arguments=arguments, stdin=stdin, compile_timeout=compile_timeout)
    end = time.time_ns() // 1_000_000
    run.require(actual.ok and not actual.stderr, "io-run", "exit 0 and empty stderr", run.output(actual))
    observed = {}
    for line in actual.stdout.splitlines():
        name, separator, value = line.partition("=")
        run.require(bool(separator) and name not in observed, "io-protocol", "unique named result", line)
        observed[name] = value
    stamp = observed.get("clock", "")
    run.require(stamp.isdecimal() and start <= int(stamp) <= end, "io-clock", "epoch milliseconds during invocation", stamp)
    observed["clock"] = None
    run.require(observed == expected, "io-reference", expected, observed)
    actual_files = {file.relative_to(directory / "data").as_posix(): file.read_bytes()
                    for file in (directory / "data").rglob("*") if file.is_file()}
    run.require(actual_files == expected_files, "io-filesystem-state",
                {name: data.hex() for name, data in expected_files.items()},
                {name: data.hex() for name, data in actual_files.items()})
    for feature in FEATURES:
        run.count("features", "io:" + feature)
