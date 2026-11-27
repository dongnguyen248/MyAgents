/** The message of an unknown thrown value, for user-facing error lines. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
