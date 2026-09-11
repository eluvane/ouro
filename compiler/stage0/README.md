<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=STAGE0&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="STAGE0 banner"
  />
</p>

# stage0 C blob

`driver_u.c` and `backend_u.c` are committed generated bootstrap seeds. They are required by `scripts/bootstrap.sh` and are not hand-written source truth.

`driver_u.c` is a packed split-frontend cone (lexer / parse_a / parse_b / parser_file / desugar / resolve / lower / compiler). Regenerate **only** through `scripts/stage_loop.sh --promote`. That loop emits `_build/stage_loop/stageN/*.c` and copies a frontend+backend fixpoint into this directory, then updates `docs/generated_artifact_hashes.sha256`.

`scripts/emit_frontend.sh` + `scripts/pack_frontend.py` remain the emit/pack tools used by the loop. The packer may still strip leftover Type apps from an old seed (`legacy-strip`). After extract.ouro `normalize_ir` is in the running backend, packer `--strict` must succeed. Do not hand-edit the packed blob.

Build the current bootstrap binary from the repository root:

```sh
sh scripts/bootstrap.sh
sh scripts/stage_loop.sh
```

The expected hashes are recorded in `docs/generated_artifact_hashes.sha256`. A regeneration pass must update the blobs and hash inventory together, with exact command evidence.

Do not edit these files by hand.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
