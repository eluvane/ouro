# Review ownership

Use the affected area to identify the review role.

| Area | Review role |
| --- | --- |
| `.github/workflows/`, CI and repository gates | CI and supply-chain maintainer |
| Compiler checking, `tests/compiler/`, `tests/compiler_*.ouro`, `quality/smith/` | Compiler and trust-boundary maintainer |
| `compiler/stage0/`, stage loop, generated hashes | Bootstrap and release maintainer |
| `runtime/`, runtime and IO host | Runtime maintainer |
| `quality/`, analyzers, lint policy | Language and static-analysis maintainer |
| Release packaging and release workflow | Release and supply-chain maintainer |
| `site/` and `.github/workflows/ouro-pages.yml` | Project maintainer |
| RFCs, compatibility, public docs | Language or project maintainer |
| Issue forms and community metadata | Triage and project maintainer |

Follow [the procedure for adding a blocking gate](../docs/ci.md#adding-a-gate).
Changes to triggers, permissions, cache publication, external actions, or
release publication require supply-chain review.
