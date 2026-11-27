// biome-ignore lint/correctness/noNodejsModules: This test uses Node assertions.
import assert from "node:assert/strict";
// biome-ignore lint/correctness/noNodejsModules: This test reads extension files.
import { lstat, readFile } from "node:fs/promises";
// biome-ignore lint/correctness/noNodejsModules: This test uses the built-in Node test runner.
import { test } from "node:test";

const extensionRoot = new URL("../", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("package.json", extensionRoot), "utf8"));

async function checkManifestFile(field, path) {
	if (typeof path !== "string" || path.length === 0) {
		throw new Error(`package.json ${field} must name a file`);
	}
	const file = new URL(path, extensionRoot);
	if (!file.href.startsWith(extensionRoot.href)) {
		throw new Error(`package.json ${field}: ${path} resolves outside the extension directory`);
	}
	if (!(await lstat(file)).isFile()) {
		throw new Error(`package.json ${field}: ${path} is not a regular file`);
	}
}

test("the extension entry point is a file", async () => {
	await checkManifestFile("main", manifest.main);
});

test("the TextMate grammar paths are files", async () => {
	const grammars = manifest.contributes?.grammars;
	assert.ok(
		Array.isArray(grammars) && grammars.length > 0,
		"package.json contributes.grammars must list a grammar",
	);
	await Promise.all(
		grammars.map((grammar, index) =>
			checkManifestFile(`contributes.grammars[${index}].path`, grammar?.path),
		),
	);
});
