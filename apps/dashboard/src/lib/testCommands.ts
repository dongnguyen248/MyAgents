/**
 * Client-side mirror of the backend's test-command argv rules
 * (checked_test_commands in the Test agent), so the common
 * mistakes in the replace-test-command input are caught before
 * the round-trip. The backend stays the authority: it
 * re-validates every replacement and answers 422 for anything
 * this mirror misses.
 *
 * Input shape: one command per line, arguments split on
 * whitespace. Arguments containing spaces cannot be expressed
 * in this input.
 */

export const MAX_TEST_COMMANDS = 20;
const MAX_ARGS_PER_COMMAND = 256;
const MAX_ARG_CHARS = 4096;

export function parseTestCommands(text: string): string[][] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.split(/\s+/));
}

/** The first problem with the commands, or undefined when valid. */
export function testCommandError(commands: string[][]): string | undefined {
  if (commands.length === 0) {
    return 'Provide at least one test command';
  }
  if (commands.length > MAX_TEST_COMMANDS) {
    return `Provide at most ${MAX_TEST_COMMANDS} test commands`;
  }
  for (const argv of commands) {
    const problem = argvError(argv);
    if (problem) {
      return problem;
    }
  }
  return undefined;
}

function argvError(argv: string[]): string | undefined {
  if (argv.length === 0 || argv.length > MAX_ARGS_PER_COMMAND) {
    return 'Each test command must be a non-empty bounded argv list';
  }
  for (const arg of argv) {
    if (arg.length === 0 || arg.length > MAX_ARG_CHARS) {
      return 'Command arguments must be non-empty bounded strings';
    }
  }
  return executableError(argv[0]);
}

function executableError(executable: string): string | undefined {
  const segments = executable.replace(/\\/g, '/').split('/');
  if (
    /^[A-Za-z]:/.test(executable) ||
    executable.startsWith('/') ||
    executable.startsWith('\\') ||
    executable.includes(':') ||
    segments.includes('..')
  ) {
    return 'Command executable must be bare or relative without parent traversal';
  }
  return undefined;
}
