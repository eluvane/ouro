# Ouro for VS Code

The extension highlights Ouro source and connects to the experimental
language server over stdio. See the
[supported language-server requests](../../docs/tooling.md#language-server).

## Build

Install Node.js and npm, and use a VS Code version compatible with
`^1.91.0` as declared in the [extension manifest](package.json). Run these
commands from the repository root. `npm ci` installs the locked dependencies
and replaces any existing `node_modules` in the extension directory.

```sh
cd editors/vscode
npm ci
npm run compile
```

Open this directory in VS Code and press `F5` to launch an Extension Development
Host.

For a local installation, copy or symlink the directory into your VS Code
extensions directory after compiling it.

## Toolchain

Build the server from the Ouro repository root using the
[source-build prerequisites](../../docs/getting_started.md#requirements).
Set the machine-scoped `ouro.server.command` to the full path to the built
executable.

```sh
sh scripts/build_tool.sh tools/lsp.ouro _build/tools/ouro-lsp
```

Open a workspace you trust. The extension starts only the command configured
in machine settings, and VS Code disables it in Restricted Mode. Set
`ouro.root` to the toolchain checkout when the first workspace folder points
elsewhere.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `ouro.root` | First workspace folder | Machine-scoped Ouro repository used by the server |
| `ouro.server.command` | disabled | Machine-scoped trusted LSP command |
| `ouro.server.args` | `[]` | Additional server arguments |
| `ouro.trace.server` | `off` | JSON-RPC tracing in the Ouro output channel |

## Troubleshooting

After rebuilding, run **Ouro: Restart Language Server** from the command
palette. If the server fails to start, check Workspace Trust and the executable
path. For protocol errors, set `ouro.trace.server` to `verbose` and inspect
the **Ouro** output channel.

The protocol suite listed in [CI](../../docs/ci.md) runs without VS Code.
