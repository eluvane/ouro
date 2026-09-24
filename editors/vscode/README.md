# Ouro for VS Code

This extension provides syntax highlighting and starts Ouro's experimental
language server.

The [language-server reference](../../docs/tooling.md#language-server)
describes supported requests and limitations.

## Build

```sh
cd editors/vscode
npm install
npm run lint
npm run compile
```

Open this directory in VS Code and press `F5` to launch an Extension Development
Host.

For a local installation, copy or symlink the directory into your VS Code
extensions directory after compiling it.

## Toolchain

Build the server, then configure its executable as the machine-scoped
`ouro.server.command` setting:

```sh
sh scripts/build_tool.sh tools/lsp.ouro _build/tools/ouro-lsp
```

The extension does not execute scripts from an opened repository and does not
start in Restricted Mode. Open a trusted workspace, set `ouro.server.command`
to the built server (or a trusted wrapper), and optionally set `ouro.root` to
the checkout directory.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `ouro.root` | First workspace folder | Machine-scoped Ouro repository used by the server |
| `ouro.server.command` | disabled | Machine-scoped trusted LSP command |
| `ouro.server.args` | `[]` | Additional server arguments |
| `ouro.trace.server` | `off` | JSON-RPC tracing in the Ouro output channel |

## Troubleshooting

Use **Ouro: Restart Language Server** after rebuilding the toolchain. Set
`ouro.trace.server` to `verbose` and inspect the **Ouro** output channel for
protocol and server errors.

The protocol suite listed in [CI](../../docs/ci.md) runs without VS Code.
