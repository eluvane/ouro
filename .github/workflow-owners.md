<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=OWNERS&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="OWNERS banner"
  />
</p>

# Review ownership

This repository does not yet map paths to named GitHub teams. Until that mapping
exists, sensitive areas are reviewed by role.

| Area | Review role |
| --- | --- |
| `.github/workflows/`, CI and repository gates | CI and supply-chain maintainer |
| Compiler checking, `tests/compiler_*.ouro`, `quality/smith/` | Compiler and trust-boundary maintainer |
| `compiler/stage0/`, stage loop, generated hashes | Bootstrap and release maintainer |
| `runtime/`, runtime and IO host | Runtime maintainer |
| `quality/`, analyzers, lint policy | Language and static-analysis maintainer |
| Release packaging and release workflow | Release and supply-chain maintainer |
| `site/` and `.github/workflows/ouro-pages.yml` | Project maintainer |
| RFCs, compatibility, public docs | Language or project maintainer |
| Issue forms and community metadata | Triage and project maintainer |

A new blocking workflow gate needs a local command, a clear report or diagnostic,
and registration in the appropriate CI profile. Changes to triggers,
permissions, cache-save behavior, external actions, or release publication need
supply-chain review.

This role map can be replaced by `CODEOWNERS` when real maintainer teams are
available.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
