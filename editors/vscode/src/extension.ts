// VS Code only starts ouro-lsp over stdio; diagnostics, hover, completion, and formatting are decided by Ouro code.

import { type ExtensionContext, type LogOutputChannel, commands, window, workspace } from "vscode";
import {
	LanguageClient,
	type LanguageClientOptions,
	type ServerOptions,
} from "vscode-languageclient/node";
import { type TrustedLaunch, trustedLaunch } from "./launch_policy";

let client: LanguageClient | undefined;
let channel: LogOutputChannel | undefined;

// The checkout the toolchain runs from: an explicit setting, else the first
// workspace folder. The server resolves relative import paths against it.
function ouroRoot(): string | undefined {
	const configured = workspace.getConfiguration("ouro").get<string>("root");
	if (configured && configured.length > 0) {
		return configured;
	}
	const folders = workspace.workspaceFolders;
	if (folders === undefined || folders.length === 0) {
		return undefined;
	}
	const [folder] = folders;
	return folder.uri.fsPath;
}

function configuredLaunch(): TrustedLaunch | undefined {
	const config = workspace.getConfiguration("ouro");
	return trustedLaunch({
		trusted: workspace.isTrusted,
		root: ouroRoot(),
		command: config.get<string>("server.command") ?? "",
		args: config.get<string[]>("server.args") ?? [],
	});
}

function languageServerEnv(root: string): NodeJS.ProcessEnv {
	// biome-ignore lint/style/noProcessEnv: the LSP child inherits the host environment
	// biome-ignore lint/correctness/noProcessGlobal: the VS Code extension host is Node
	const env = { ...process.env };
	env.OURO_ROOT = root;
	return env;
}

function serverOptions(launch: TrustedLaunch): ServerOptions {
	return {
		command: launch.command,
		args: launch.args,
		options: {
			cwd: launch.root,
			env: languageServerEnv(launch.root),
		},
	};
}

function clientOptions(root: string): LanguageClientOptions {
	return {
		documentSelector: [{ scheme: "file", language: "ouro" }],
		// Diagnostics come from a whole-cone typecheck, so an edit to an
		// imported module changes them even when it is not the open document.
		synchronize: {
			fileEvents: workspace.createFileSystemWatcher("**/*.ouro"),
		},
		outputChannel: channel,
		initializationOptions: { root },
	};
}

async function start(): Promise<void> {
	if (!workspace.isTrusted) {
		window.showWarningMessage(
			"Ouro: the language server is disabled until this workspace is trusted.",
		);
		return;
	}
	const launch = configuredLaunch();
	if (launch === undefined) {
		window.showWarningMessage(
			"Ouro: set the machine-scoped ouro.server.command and open a folder (or set ouro.root) to start the language server.",
		);
		return;
	}
	client = new LanguageClient(
		"ouro",
		"Ouro Language Server",
		serverOptions(launch),
		clientOptions(launch.root),
	);
	try {
		await client.start();
	} catch (err) {
		client = undefined;
		window.showErrorMessage(`Ouro: language server failed to start: ${err}`);
	}
}

async function stop(): Promise<void> {
	const running = client;
	client = undefined;
	if (running !== undefined) {
		await running.stop();
	}
}

export async function activate(context: ExtensionContext): Promise<void> {
	channel = window.createOutputChannel("Ouro", { log: true });
	context.subscriptions.push(channel);
	context.subscriptions.push(
		commands.registerCommand("ouro.restartServer", async () => {
			await stop();
			await start();
		}),
	);
	await start();
}

export async function deactivate(): Promise<void> {
	await stop();
}
