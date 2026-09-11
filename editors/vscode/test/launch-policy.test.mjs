// biome-ignore lint/correctness/noNodejsModules: This test runs in Node and uses its assertion API.
import assert from "node:assert/strict";
// biome-ignore lint/correctness/noNodejsModules: These cases use the built-in Node test runner.
import { test } from "node:test";
import { trustedLaunch } from "../out/launch_policy.js";

test("an untrusted workspace must never produce a process launch", () => {
	assert.equal(
		trustedLaunch({ trusted: false, root: "/workspace", command: "/opt/ouro-lsp", args: [] }),
		undefined,
	);
});

test("workspace scripts are not an implicit executable fallback", () => {
	assert.equal(
		trustedLaunch({ trusted: true, root: "/workspace", command: "", args: [] }),
		undefined,
	);
});

test("launch needs an explicit or open workspace root", () => {
	assert.equal(
		trustedLaunch({ trusted: true, root: undefined, command: "/opt/ouro-lsp", args: [] }),
		undefined,
	);
});

test("an explicit trusted command preserves its root and arguments", () => {
	assert.deepEqual(
		trustedLaunch({ trusted: true, root: "/workspace", command: " /opt/ouro-lsp ", args: ["--stdio"] }),
		{ root: "/workspace", command: "/opt/ouro-lsp", args: ["--stdio"] },
	);
});
