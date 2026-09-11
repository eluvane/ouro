export interface LaunchInput {
	trusted: boolean;
	root: string | undefined;
	command: string;
	args: readonly string[];
}

export interface TrustedLaunch {
	root: string;
	command: string;
	args: string[];
}

// A workspace may choose source and imports, but it may not choose the program
// the editor executes. The command is a machine-scoped setting and an empty
// value deliberately means "do not launch".
export function trustedLaunch(input: LaunchInput): TrustedLaunch | undefined {
	const command = input.command.trim();
	if (!input.trusted || input.root === undefined || command.length === 0) {
		return undefined;
	}
	return { root: input.root, command, args: [...input.args] };
}
