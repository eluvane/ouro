<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=VS%20CODE&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="VS CODE banner"
  />
</p>

# Ouro for VS Code

This extension provides syntax highlighting and starts Ouro's experimental
language server.

## Features

- diagnostics on open, full-document change, and save;
- hover information;
- go to definition;
- completion;
- document and workspace symbols;
- whole-buffer rename;
- document formatting;
- Ouro syntax highlighting.

The language server uses the same checker and formatter as the command line. It
is not an incremental typechecker; document changes are synchronized as complete
buffers and several requests rebuild an index from the open file and imports.

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

The protocol regression suite runs without VS Code:

```sh
sh scripts/lsp_suite.sh
```

See [`docs/tooling.md`](../../docs/tooling.md) for the current language-server
capabilities and limitations.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
