# stage0 C blob

`driver_u.c` and `backend_u.c` are committed generated bootstrap inputs, not
handwritten source. `driver_u.c` packs the split frontend: lexer, parsers,
desugaring, resolution, lowering, and compiler. The stage loop calls
`scripts/frontend_regen.py`, which packs the frontend with
`scripts/pack_frontend.py --strict`. `scripts/emit_frontend.sh` remains the
standalone regeneration entry point. Strict packing rejects leftover Type
applications; `compiler/extract.ouro`'s `normalize_ir` owns their removal.

Do not edit the C files by hand. [Build](../../docs/build.md#generated-artifacts-and-stage-loop)
owns regeneration, promotion, coordinated bootstrap-input updates, hashes, and
command evidence.
