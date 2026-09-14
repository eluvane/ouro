"""Parameterized stdlib contracts whose answers come from Python specifications."""
from __future__ import annotations

import hashlib
import hmac
import csv
import io
import json
import os
import posixpath

from ourosmith import ROOT
from ourosmith.host import BUILD_TIMEOUT_S
from ourosmith.surface.practical import application, workflow


def quote(value):
    return json.dumps(value, ensure_ascii=True)


def string_list(values):
    return f'([{", ".join(map(quote, values))}] : List String)'


def strings(seed):
    word, count = f"value{seed}", 2 + seed % 4
    text = word + ",second,,last,"
    for count_arg in (0, 3, len(word) + 2):
        yield f"str_take {quote(word)} {count_arg}", word[:count_arg]
        yield f"str_drop {quote(word)} {count_arg}", word[count_arg:]
    yield f"str_repeat {quote(word)} {count}", word * count
    yield f'str_join "|" (str_split_str {quote(text)} ",")', "|".join(text.split(","))
    yield f'str_join "|" (str_split {quote(text)} 44)', "|".join(text.split(","))
    yield 'show_nat (length String (str_split "" 44))', "1"
    yield f'str_before {quote(word + "=result")} "="', word
    yield f'str_after {quote(word + "=result")} "="', "result"
    for actual, prefix, suffix in (("--" + word + ".ouro", "--", ".ouro"), (word, "missing", ".bad")):
        yield f'fromMaybe String "?" (str_strip_prefix {quote(actual)} {quote(prefix)})', actual[len(prefix):] if actual.startswith(prefix) else "?"
        yield f'fromMaybe String "?" (str_strip_suffix {quote(actual)} {quote(suffix)})', actual[:-len(suffix)] if actual.endswith(suffix) else "?"
    for pattern in ("", word[:3], word[-2:], word, word + "long", "missing"):
        for function, expected in (("str_starts", word.startswith(pattern)), ("str_ends", word.endswith(pattern)), ("str_contains", pattern in word)):
            yield f"show_bool ({function} {quote(word)} {quote(pattern)})", str(expected).lower()
        index = word.find(pattern)
        yield f' show_nat (fromMaybe Nat 99 (str_index {quote(word)} {quote(pattern)}))', str(index if index >= 0 else 99)
    repeated = "a" * (count + 2)
    yield f'show_nat (str_count {quote(repeated)} "aa")', str(len(repeated) - 1)
    yield f'str_replace {quote(repeated)} "aa" "b"', repeated.replace("aa", "b")
    yield f'str_replace {quote(word)} "" "x"', word
    yield f'str_replace {quote(word)} "missing" "x"', word
    spaced = f"  {word}\tsecond\nthird  "
    yield f'str_join "|" (str_tokens {quote(spaced)})', "|".join(spaced.split())
    yield 'show_nat (length String (str_tokens " \\t\\r\\n "))', "0"
    for a, b in ((word, word), (word, word + "z"), (word + "z", word)):
        yield f'show_bool (str_le {quote(a)} {quote(b)})', str(a <= b).lower()
        yield f'show_bool (str_lt {quote(a)} {quote(b)})', str(a < b).lower()
    items = [word, "b", "a", word, "b"]
    yield f'str_join "," (str_sort_uniq {string_list(items)})', ",".join(sorted(set(items)))
    yield f'str_indent {count} {quote(word)}', " " * count + word
    yield f'show_nat (length String (str_lines (str_unlines {string_list([word, "other"])})))', "2"
    yield f'str_slice {quote(word)} 1 3', word[1:4]
    yield f'str_of_codes (str_codes {quote(word)})', word
    yield f'str_upper {quote(word + " Mixed")}', (word + " Mixed").upper()


def helpers(seed):
    # ASCII lexical specification, including each class boundary and apostrophe.
    codes = [0, 32, 38, 39, 40, 47, 48, 57, 58, 64, 65, 90, 91, 94, 95, 96, 97, 122, 123, 127]
    codes += [65 + seed % 26, 97 + seed % 26, 48 + seed % 10]
    for code in codes:
        start = 65 <= code <= 90 or 97 <= code <= 122 or code == 95
        for function, expected in [('is_ident_start', start), ('is_ident_cont', start or 48 <= code <= 57 or code == 39)]:
            yield f'show_bool ({function} {code})', str(expected).lower()
    name, detail = f'case{seed}', f'expected{seed}'
    yield f'test_line (test_ok {quote(name)})', 'ok ' + name
    for reason in ('', detail):
        yield f'test_line (test_fail {quote(name)} {quote(reason)})', 'FAIL ' + name + (' ' + reason if reason else '')
    for boolean, expected in [('True', False), ('False', True)]:
        yield f'show_bool (test_failed (assert_true {quote(name)} {boolean}))', str(expected).lower()
    for actual in (detail, detail + 'bad'):
        yield f'show_bool (test_failed (assert_eq {quote(name)} {quote(actual)} {quote(detail)}))', str(actual != detail).lower()


def paths(seed):
    directory, name = f"dir{seed}/nested", f"file{seed}.ouro"
    path = directory + "/" + name
    for function, expected in (("path_basename", name), ("path_dirname", directory), ("path_ext", ".ouro"), ("path_stem", name[:-5])):
        yield f'{function} {quote(path)}', expected
    for path_arg in ("Makefile", ".hidden"):
        yield f'path_ext {quote(path_arg)}', ""
    for path_arg in (path, path + ".js"):
        yield f'show_bool (path_ends_ouro {quote(path_arg)})', str(path_arg.endswith(".ouro")).lower()
    for base, target, expected in ((directory, path, name), ("elsewhere", path, path), (".", ".github/workflows/x.yml", ".github/workflows/x.yml"),
                                    (directory, directory, ""), ("a", "apple", "apple"), ("/data", "/database/x", "/database/x")):
        yield f'path_relative {quote(base)} {quote(target)}', expected
    for base, target, expected in ((directory, path, True), ("_build/", "_build/tmp/x", True), ("a", "apple", False), ("/data", "/database", False)):
        yield f'show_bool (path_under {quote(base)} {quote(target)})', str(expected).lower()
    for spelling in (directory + "/./x/../y", "C:/tmp/./x/../y"):
        yield f'path_normalize {quote(spelling)}', posixpath.normpath(spelling)
    yield 'path_normalize "C:/../"', "C:/"
    yield 'path_dirname "C:/tmp/x.ouro"', "C:/tmp"
    yield 'path_relative "C:\\\\tmp\\\\root" "C:/tmp/root/a.ouro"', "a.ouro"
    yield 'path_from_host "a\\\\b\\\\c"', "a/b/c"
    for spelling in ("/data/x", "C:/data/x", "a/b"):
        yield f'show_bool (path_is_abs {quote(spelling)})', str(spelling.startswith("/") or ":/" in spelling).lower()


def data(seed):
    pairs = [("c", str(seed)), ("a", str(seed + 1)), ("b", str(seed + 2))]
    expression = "map_empty String"
    for key, value in pairs:
        expression = f"map_insert String {quote(key)} {quote(value)} ({expression})"
    yield f'str_join "," (map_keys String ({expression}))', "a,b,c"
    yield f'map_get_or String "?" "b" ({expression})', str(seed + 2)
    yield f'map_get_or String "?" "missing" ({expression})', "?"
    yield f'show_nat (map_size String ({expression}))', "3"
    yield f'show_nat (map_size String (map_delete String "a" ({expression})))', "2"
    yield f'map_get_or String "?" "a" (map_insert String "a" "new" ({expression}))', "new"
    major, minor, patch = 1 + seed % 4, 1 + seed % 3, seed % 5
    base = f"{major}.{minor}.{patch}"
    for value, expected in ((base, base), (str(major), f"{major}.0.0"), (base + ".4", "?")):
        yield f'maybe Semver String "?" sv_show (sv_parse {quote(value)})', expected
    for range_value, version, expected in (("^" + base, f"{major}.{minor + 1}.0", True), ("^" + base, f"{major + 1}.0.0", False),
                                          ("^0.2.3", "0.3.0", False), ("~" + base, f"{major}.{minor}.{patch + 1}", True),
                                          ("~" + base, f"{major}.{minor + 1}.0", False), (">=" + base, base, True),
                                          (">" + base, base, False), ("<" + base, f"{major}.{minor - 1}.0", True),
                                          ("*", base, True), (base, base, True)):
        yield f'show_bool (sv_matches {quote(range_value)} {quote(version)})', str(expected).lower()
    versions = [f"{major - 1}.0.0", base, f"{major}.{minor + 1}.0", f"{major + 1}.0.0"]
    yield f'fromMaybe String "none" (sv_best_str "^{major}.0.0" {string_list(versions)})', versions[2]
    argv = "args_of_argv " + string_list(["ouro", "pkg", "install", "--registry", f"registry{seed}", "--force", f"--jobs={major}", "-v", "--", "--not-a-flag"])
    yield f'args_cmd ({argv})', "pkg"
    yield f'str_join "," (args_positional ({argv}))', "pkg,install,--not-a-flag"
    yield f'args_opt_or ({argv}) "registry" "?"', f"registry{seed}"
    yield f'args_opt_or ({argv}) "jobs" "?"', str(major)
    for flag, expected in (("force", True), ("v", True), ("quiet", False)):
        yield f'show_bool (args_flag ({argv}) {quote(flag)})', str(expected).lower()
    for bools, argv, expected in (([], ["tool", "--registry", "local"], True), ([], ["tool", "--jobs=2"], True),
                                 (["list"], ["tool", "--list"], True), ([], ["tool", "--registry"], False),
                                 (["list"], ["tool", "--registry", "--list"], False), ([], ["tool", "--", "--registry"], True)):
        yield f'show_bool (args_argv_options_complete ([{", ".join(map(quote, bools))}] : List String) ([{", ".join(map(quote, argv))}] : List String))', str(expected).lower()
    yield 'maybe String String "missing" (fun (x : String) => x) (args_opt (args_parse (["--registry"] : List String)) "registry")', "missing"
    yield 'show_bool (args_flag (args_parse (["--registry"] : List String)) "registry")', "false"


def crypto(seed):
    for a, b in ((1, 3), (7, 3), (seed % 256, (seed * 7) % 256)):
        yield f'show_nat (xor32 {a} {b})', str(a ^ b)
        yield f'show_nat (and32 {a} {b})', str(a & b)
    for value in ("", "abc", f"seed{seed}"):
        yield f'sha256 {quote(value)}', hashlib.sha256(value.encode()).hexdigest()
    for key, value in (("", ""), (f"key{seed}", f"message{seed}")):
        yield f'hmac_sha256 {quote(key)} {quote(value)}', hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def protocols(seed):
    # Seeds choose bounded values; their magnitude is not Peano literal fuel.
    number = seed % 100
    values = [seed % 50, -(seed % 20 + 1), 1.5, 0, True, None,
              f'value{seed}\n"quoted"', [], {}, [seed % 10, False], {"key": f"value{seed}"}]
    for value in values:
        source = compact(value)
        parsed = f"parse_json {quote(source)}"
        yield f'maybe Json String "rejected" json_print ({parsed})', source
    for source in ("--1", "1.2.3", "-", "1.", "01", '"\\q"', '[1,]', '[1, \n ]', '{"x":1,}', '{"x":[1,]}', '{"x":}', 'true false'):
        yield f'show_bool (maybe Json Bool False (fun (_value : Json) => True) (parse_json {quote(source)}))', "false"
    request = {"jsonrpc": "2.0", "id": number, "method": f"ping{seed}", "params": {"n": number + 1}}
    body = compact(request)
    frame = f"Content-Length: {len(body.encode())}\r\n\r\n{body}"
    yield f'json_print (JStr (rpc_frame {quote(body)}))', compact(frame)
    for accessor, expected in (("fst", body), ("snd", "tail")):
        yield f'maybe (Pair String String) String "incomplete" ({accessor} String String) (rpc_take {quote(frame + "tail")})', expected
    message = f"fromMaybe Json JNull (parse_json {quote(body)})"
    yield f'rpc_method ({message})', request["method"]
    yield f'show_nat (json_nat_or (rpc_id ({message})) 0)', str(number)
    yield f'show_nat (json_field_nat (rpc_params ({message})) "n" 0)', str(number + 1)
    yield f'show_bool (rpc_is_notification ({message}))', "false"
    yield f'show_bool (rpc_is_notification (rpc_notify "ping" (json_num {number})))', "true"
    yield f'json_print (rpc_result (json_num {number}) (JStr "pong"))', compact({"jsonrpc": "2.0", "id": number, "result": "pong"})
    yield f'json_print (rpc_error (json_num {number}) rpc_err_method_not_found "nope")', compact({"jsonrpc": "2.0", "id": number, "error": {"code": -32601, "message": "nope"}})
    for incomplete in ("Content-Length: 99\r\n\r\n{}", "{}", "Content-Length: bad\r\n\r\n{}", frame[:-1]):
        yield f'show_bool (maybe (Pair String String) Bool False (fun (_value : Pair String String) => True) (rpc_take {quote(incomplete)}))', "false"
    text = f"body{seed}"
    headers = '([MkPair String String "Content-Type" "text/plain"] : List (Pair String String))'
    for method, target in (("POST", f"/echo{seed}"), ("POST\r\n", "/echo"), ("POST", "/x\r\nX: y")):
        expected = f"{method} {target} HTTP/1.0\r\nContent-Type: text/plain\r\nContent-Length: {len(text)}\r\n\r\n{text}" if "\r" not in method + target else ""
        yield f'json_print (JStr (render_request (MkHttpReq {quote(method)} {quote(target)} {headers} {quote(text)})))', compact(expected)
    for code in (200, 299, 300, 404):
        response = f"HTTP/1.0 {code} Status\r\nContent-Type: text/plain\r\n\r\n{text}"
        parsed = f"parse_response {quote(response)}"
        yield f'show_nat (http_status ({parsed}))', str(code)
        yield f'http_body ({parsed})', text
        yield f'show_bool (http_ok ({parsed}))', str(200 <= code < 300).lower()
    for bad in ("HTTP/1.0 200 OK\r\nNotAHeader\r\n\r\nbody", "hello\n\nbody"):
        yield f'http_reason (parse_response {quote(bad)})', "unparsed"


def tables(seed):
    header = ["name", "status"]
    row = [f"value{seed}", "ok"]
    for actual in (row[:1], row):
        yield f'fromMaybe String "missing" (table_cell {string_list(header)} {string_list(actual)} "status")', actual[1] if len(actual) > 1 else "missing"
    for names, expected in ((["name"], False), ([], True)):
        yield f'show_bool (validation_is_valid String (List (List String)) (tablex_project_required (Nil (List String)) {string_list(names)}))', str(expected).lower()
    table = "name,status\n" + ",".join(row) + "\n"
    for source, names, expected in ((table, header, True), ("", ["name"], False), ("name\na\n", header, False)):
        yield f'show_bool (validation_is_valid String String (tablex_csv_project_required {quote(source)} {string_list(names)}))', str(expected).lower()
    fields = [f"value{seed}", "a,b", 'a"b', ""]
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerow(fields)
    encoded = output.getvalue().removesuffix("\n")
    yield f'csv_join_row {string_list(fields)}', encoded
    yield f'str_join "|" (csv_split_row {quote(encoded)})', "|".join(fields)
    yield f'tablex_csv_project {quote(table)} {string_list(list(reversed(header)))}', "status,name\nok," + row[0]


FAMILIES = {"strings": (strings, ("std/text.ouro",)), "paths": (paths, ("std/pathx.ouro",)),
            "data": (data, ("std/map.ouro", "std/semver.ouro", "std/args.ouro")), "crypto": (crypto, ("std/crypto.ouro",)),
            "protocols": (protocols, ("std/jsonrpc.ouro", "std/http.ouro")), "tables": (tables, ("std/tablex.ouro",)),
            "helpers": (helpers, ("std/char.ouro", "std/test.ouro")),
            "workflow": (workflow, ("std/practical.ouro",)), "application": (application, ("tools/app_surface_lib.ouro",))}


def run_family(run, directory, family, saved=None):
    generate, modules = FAMILIES[family]
    rows = [] if saved is not None and "source" in saved else list(generate(run.seed))
    run_expressions(run, directory, "stdlib_" + family, rows,
                    list(modules), "stdlib-" + family, saved=saved)
    run.count("features", "stdlib:" + family)


def run_expressions(run, directory, recipe, rows, modules, property_name, *, saved=None, definitions=""):
    from frontend_regen import collect_units

    source_root = run.overrides.get("source-root", ROOT)
    imports = "".join(f'import {quote(os.path.relpath(source_root / name, directory).replace(chr(92), "/"))};\n'
                      for name in ("std/io.ouro", "std/format.ouro", *modules))
    declarations = "".join(f"def observed{i} : String := {expression};\n" for i, (expression, _) in enumerate(rows))
    actions = "\n".join(f"     println observed{i};" for i in range(len(rows)))
    source = definitions + declarations + "\n-- @entry main\ndef main : IO Unit :=\n  do\n" + actions + "\n     exit 0\n"
    expected = "".join(value + "\n" for _, value in rows)
    if saved is not None and "source" in saved:
        source, expected = saved["source"], saved["expected_stdout"]
    run.input = {"recipe": recipe, "seed": run.seed, "source": source, "expected_stdout": expected}
    path = directory / "main.ouro"
    path.write_text(imports + source, encoding="utf-8", newline="\n")
    units = collect_units(path.as_posix())
    # Integration recipes check and compile their complete stdlib source cone.
    compile_timeout = BUILD_TIMEOUT_S
    run.accepts(path, artifact=False, units=units, timeout=compile_timeout)
    actual = run.native(path, units=units, io=True, compile_timeout=compile_timeout)
    run.require(actual.ok and actual.stdout == expected and not actual.stderr,
                property_name, expected, run.output(actual))
