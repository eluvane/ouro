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

A new blocking workflow gate follows [CI policy](../docs/ci.md#adding-a-gate).
Changes to triggers, permissions, cache-save behavior, external actions, or
release publication need supply-chain review.

This role map can be replaced by `CODEOWNERS` when real maintainer teams are
available.
