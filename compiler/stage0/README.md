# Stage0 bootstrap inputs

`driver_u.c` and `backend_u.c` are generated C inputs. `driver_u.c` contains
the lexer, parsers, desugaring, import resolution, lowering, and compiler from
the split frontend.

Regenerate and promote these files through the
[stage-loop procedure](../../docs/build.md#generated-artifacts-and-stage-loop).
That procedure covers bootstrap-input changes, hashes, and required checks.

The stage loop uses `scripts/emit_frontend.sh` and `scripts/pack_frontend.py`.
The legacy stripping step can remove leftover `Type` applications from old
seeds. A backend with `normalize_ir` from `extract.ouro` must pass the packer
with `--strict`.
