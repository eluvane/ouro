"""Independent value and error contracts for practical composition helpers."""
from __future__ import annotations

import json


def quote(value):
    return json.dumps(value)


def workflow(seed):
    number = 1 + seed % 9
    for start, end in ((number, number + 3), (number, number), (number + 1, number)):
        yield f'str_join "," (map Nat String show_nat (nat_range_closed {start} {end}))', ",".join(map(str, range(start, end + 1)))
    values = [number + i for i in range(5)]
    source_values = "([" + ", ".join(map(str, values)) + "] : List Nat)"
    for size in (0, 1, 2, 9):
        chunks = [values[i:i + size] for i in range(0, len(values), size)] if size else []
        render = '(fun (row : List Nat) => str_join "," (map Nat String show_nat row))'
        yield f'str_join "|" (map (List Nat) String {render} (chunks_of Nat {size} {source_values}))', "|".join(
            ",".join(map(str, row)) for row in chunks)
    for spelling, expected in (("yes", "true"), ("no", "false"), ("", "invalid"), ("maybe", "invalid")):
        yield f'match str_parse_bool {quote(spelling)} with | Nothing => "invalid" | Just value => show_bool value end', expected
    text = f"limit={number}\nenabled=yes\npath=input{seed}.txt\n"
    cfg = f"config_parse {quote(text)}"
    yield f'show_nat (result_or ConfigError Nat 99 (config_get_nat ({cfg}) "limit"))', str(number)
    yield f'show_bool (config_get_bool_or ({cfg}) "enabled" False)', "true"
    for kind, source in (("String", f'config_require ({cfg}) "missing"'),
                         ("Nat", 'config_get_nat (config_parse "limit=many") "limit"')):
        yield f'show_bool (result_is_err ConfigError {kind} ({source}))', "true"
    for fields, valid in ((['configx_field "limit" ConfigAsNat', 'configx_field "enabled" ConfigAsBool'], True),
                          (['configx_field "path" ConfigAsNat'], False),
                          (['configx_field "missing" ConfigAsString'], False)):
        schema = "([" + ", ".join(fields) + "] : List ConfigField)"
        yield f'show_bool (validation_is_valid ConfigError Unit (configx_validate_schema ({cfg}) {schema}))', str(valid).lower()
    for value in (str(number), "many"):
        args = f'cli_parse (["verbose"] : List String) (["run", "--limit", {quote(value)}, "--verbose"] : List String)'
        yield f'show_bool (cli_flag ({args}) "verbose")', "true"
        yield f'show_bool (result_is_err CliError Nat (cli_required_nat ({args}) "limit"))', str(value == "many").lower()
    for function, operation in (("nat_div_checked", lambda a, b: a // b), ("nat_mod_checked", lambda a, b: a % b)):
        for divisor in (0, 1, 3):
            expr = f"{function} {number} {divisor}"
            yield f'show_bool (result_is_err String Nat ({expr}))', str(divisor == 0).lower()
            if divisor:
                yield f'show_nat (result_or String Nat 99 ({expr}))', str(operation(number, divisor))
    source = f" # ignored\n\n{number}\n {number + 1}\nword\n"
    lines = f'line_data_lines "#" (lines_from_text {quote(source)})'
    yield f'show_nat (length String ({lines}))', "3"
    yield f'show_nat (length Nat (line_nat_values ({lines})))', "2"
    yield f'str_join "," (map Nat String show_nat (line_nat_values ({lines})))', f"{number},{number + 1}"
    yield f'str_join "," (map LineRecord String (fun (row : LineRecord) => show_nat (line_record_number row)) (line_number ({lines})))', "1,2,3"
    obj = json.dumps({"data": {"limit": number}}, separators=(",", ":"))
    parsed = f"fromMaybe Json JNull (parse_json {quote(obj)})"
    yield f'show_nat (fromMaybe Nat 99 (jsonx_path_nat ({parsed}) (["data", "limit"] : List String)))', str(number)
    yield f'show_nat (fromMaybe Nat 99 (jsonx_path_nat ({parsed}) (["missing"] : List String)))', "99"
    for bits in ((True, True), (False, True), (False, False)):
        entries = [f'validation_require String "error{i}" {bit!s}' for i, bit in enumerate(bits)]
        value = 'validation_collect_unit String ([' + ", ".join(entries) + '] : List (Validation String Unit))'
        yield f'show_nat (length String (validation_errors String Unit ({value})))', str(bits.count(False))
        yield f'show_bool (validation_is_valid String Unit ({value}))', str(all(bits)).lower()
    command = f'command_add_arg (command_spec "echo" (["first"] : List String)) "value{seed}"'
    yield f'command_render ({command})', f"echo first value{seed}"
    yield f'command_dry_run ({command})', f"dry-run: echo first value{seed}"
    yield f'show_nat (length CommandSpec (process_plan_commands (process_plan_add process_plan_empty ({command}))))', "1"
    context = f'command_context "tool{seed}" (cli_parse (Nil String) (Nil String)) ({cfg})'
    yield f'command_context_program ({context})', f"tool{seed}"
    report = f'report_add "plan" (command_render ({command})) (report_add_nat "line_values" {number} report_empty)'
    completed = f'command_report ({context}) ({report})'
    yield f'report_render ({completed})', f"program=tool{seed}\nline_values={number}\nplan=echo first value{seed}"
    yield f'show_bool (result_is_ok CommandError Report (command_ok ({completed})))', "true"
    yield 'show_bool (result_is_err CommandError Report (command_fail (CommandUsage "bad")))', "true"
    yield f'workspace_root (MkWorkspace "_build/workspace{seed}")', f"_build/workspace{seed}"
    for constructor, expected in (("CommandUsage", 2), ("CommandMessage", 1)):
        yield f'show_nat (command_exit_code ({constructor} "detail{seed}"))', str(expected)


def application(seed):
    name, number = f"row{seed}", seed % 11
    for valid, source in ((True, json.dumps({"ok": True})), (False, '{"ok":}')):
        yield f'json_print (app_json_validate_report {quote(source)})', json.dumps(
            {"kind": "ouro.app_surface.json.validate", "pass": valid, "message": "valid_json" if valid else "invalid_json"}, separators=(",", ":"))
    table = f"name,count\n{name},{number}\n"
    rows = f'csv_parse {quote(table)}'
    yield f'result_or AppSurfaceError String "error" (app_csv_select_column ({rows}) "name")', name
    yield f'show_bool (result_is_err AppSurfaceError String (app_csv_select_column ({rows}) "missing"))', "true"
    yield f'result_or AppSurfaceError String "error" (app_tsv_from_csv_columns ({rows}) (["count", "name"] : List String))', f"count\tname\n{number}\t{name}"
    for relative, safe in ((f"safe/{name}.json", True), ("../outside", False), ("/absolute", False)):
        value = f'app_path_within_workspace "_build/workspace" {quote(relative)}'
        yield f'show_bool (result_is_ok FsError String ({value}))', str(safe).lower()
        if safe:
            yield f'result_or FsError String "error" ({value})', "_build/workspace/" + relative
