# Ouro for VS Code

This extension provides syntax highlighting and starts Ouro's experimental
language server.

The [language-server reference](../../docs/tooling.md#language-server)
describes supported requests and limitations.

## Build

```sh
cd editors/vscode
npm ci
npm test
```

Open this directory in VS Code and press `F5` to launch an Extension Development
Host.

For a local installation, copy or symlink the directory into your VS Code
extensions directory after compiling it.

## Toolchain

Build `ouro-lsp.exe` and `ouro-fmt.exe` with the
[standalone native tool commands](../../docs/tooling.md#standalone-native-tools).
Keep them beside `coil.exe` and its `ouro-native-build.exe` backend, then set the
machine-scoped `ouro.server.command` to the server's absolute path.

The extension starts the configured command only in a trusted workspace. It
uses `ouro.root` (or the first workspace folder) as the working directory and
`OURO_ROOT` authorization boundary. That root needs an existing `_build`
directory for unsaved-buffer checks and formatting.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `ouro.root` | First workspace folder | Machine-scoped working directory and `OURO_ROOT` authorization boundary |
| `ouro.server.command` | disabled | Machine-scoped trusted LSP command |
| `ouro.server.args` | `[]` | Machine-scoped additional server arguments |
| `ouro.trace.server` | `off` | JSON-RPC tracing in the Ouro output channel |

## Troubleshooting

Use **Ouro: Restart Language Server** after rebuilding the toolchain. Set
`ouro.trace.server` to `verbose` and inspect the **Ouro** output channel for
protocol and server errors.

The protocol suite listed in [CI](../../docs/ci.md) runs without VS Code.
