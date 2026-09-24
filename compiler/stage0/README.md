# stage0 C blob

`driver_u.c` and `backend_u.c` are committed generated bootstrap inputs, not
handwritten source. `driver_u.c` packs the split frontend: lexer, parsers,
desugaring, resolution, lowering, and compiler. The stage loop uses
`scripts/emit_frontend.sh` and `scripts/pack_frontend.py`; its `legacy-strip`
path may remove leftover Type applications from an old seed. Once the running
backend has `extract.ouro`'s `normalize_ir`, packer `--strict` must succeed.

Do not edit the C files by hand. [Build](../../docs/build.md#generated-artifacts-and-stage-loop)
owns regeneration, promotion, coordinated bootstrap-input updates, hashes, and
command evidence.
