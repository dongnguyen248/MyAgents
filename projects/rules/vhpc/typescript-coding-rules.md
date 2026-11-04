# TypeScript and React Coding Rules (p-vhpc)

These rules apply to the React frontend. The [Constitution](../constitution.md)
takes precedence; follow existing feature patterns and the configured ESLint,
Prettier, and TypeScript settings rather than changing project-wide tooling as
part of an unrelated feature.

---

## 1. General Principles

1. Write code that is easy to read, review, test, and maintain.
2. Prefer explicit and safe types over implicit behavior.
3. Keep functions small and focused on a single responsibility.
4. Use the existing project patterns before introducing a new abstraction.
5. Avoid duplicated logic, unnecessary complexity, and hidden side effects.

---

## 2. Language and Compiler Rules

- Use the TypeScript version defined by the project.
- Preserve the project's `strict` setting; do not weaken compiler or lint
  checks to make a feature pass. Propose broader compiler changes separately,
  with impact analysis for existing code.
- Prefer ES modules and the project-supported module system.
- Use the configured formatter and linter as the source of truth for automated style checks.

---

## 3. Naming Conventions

### 3.1 Files and Directories

- Match the existing naming pattern for each kind of file: PascalCase React
  components (such as `CreateBiddingForm.tsx`), established lowercase
  page/API/schema names, and kebab-case where that feature uses it.
- Use names that describe the feature or responsibility.
- Colocate new test files with their source as the Constitution requires;
  do not add new `__tests__/` directories.

Examples:

```text
CreateBiddingForm.tsx
create-bidding.api.ts
create-bidding.schema.ts
CreateBiddingForm.test.tsx
```

### 3.2 Classes, Interfaces, Types, and Enums

- Use PascalCase for classes, interfaces, type aliases, and enums.
- Use nouns or noun phrases for data structures.
- Do not add an `I` prefix to interface names.
- Prefer type aliases for object shapes and unions unless a class or interface is required by the design.

Example:

```ts
interface BoardRepository {
  findById(boardId: string): Promise<Board | undefined>;
}

type TaskStatus = 'TODO' | 'IN_PROGRESS' | 'DONE';

class BoardService {}
```

### 3.3 Functions, Methods, Variables, and Parameters

- Use lowerCamelCase.
- Use verb-based names for functions and methods.
- Use meaningful names instead of unexplained abbreviations.
- Avoid single-letter names except for simple indexes or well-known callback parameters.

Example:

```ts
const taskTitle = 'Prepare release';
const retryCount = 3;

function createTask(title: string): Task {
  return { id: crypto.randomUUID(), title, status: 'TODO' };
}
```

### 3.4 Constants

- Use `UPPER_SNAKE_CASE` for module-level constants that represent fixed configuration or limits.
- Use lowerCamelCase for local values that are not global constants.

Example:

```ts
const MAX_TASKS_PER_BOARD = 50;
const defaultTaskStatus: TaskStatus = 'TODO';
```

### 3.5 Boolean Values

Use names that clearly express a condition:

```ts
const isLoading = true;
const hasPermission = false;
const shouldRetry = true;
```

---

## 4. Formatting Rules

### 4.1 Indentation and Braces

- Follow the repository's Prettier settings (currently two spaces, single
  quotes, semicolons, trailing commas, and print width 100).
- Do not use tabs.
- Put opening braces on the same line as the declaration or condition.

Example:

```ts
if (isValid) {
  saveTask();
} else {
  showError();
}
```

### 4.2 Semicolons and Quotes

- Follow the configured ESLint and Prettier settings consistently.
- Use one quote style throughout the project.
- Do not mix formatting styles within the same module.

### 4.3 Line Length and Blank Lines

- Follow the configured Prettier print width rather than a competing limit.
- Use blank lines to separate logical sections.
- Keep one blank line between functions and major declarations.
- Do not place multiple statements on one line.

### 4.4 Imports

- Keep imports at the top of the file.
- Remove unused imports.
- Prefer project path aliases when they are configured.
- Keep import ordering consistent with the project formatter.
- Avoid circular dependencies.

---

## 5. Type Safety

### 5.1 Avoid `any`

- Prefer precise types over `any` in new application code, even where the
  current linter permits it. Do not widen types just to silence errors.
- Use a precise type, generic, union, or `unknown` instead.
- If an unsafe external value must be handled, isolate and document the boundary.

Bad example:

```ts
function parseResponse(value: any): Task {
  return value;
}
```

Good example:

```ts
function parseResponse(value: unknown): Task {
  if (!isTask(value)) {
    throw new Error('Invalid task response');
  }

  return value;
}
```

### 5.2 Prefer Narrow Types

- Use union types for finite values.
- Use discriminated unions for states with different data requirements.
- Avoid broad `string` types when only a fixed set of values is valid.

Example:

```ts
type RequestState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: Task[] }
  | { status: 'error'; message: string };
```

### 5.3 Null and Undefined

- Handle `null` and `undefined` explicitly.
- Do not use non-null assertions (`!`) unless the invariant is guaranteed and documented by the surrounding code.
- Prefer optional chaining and nullish coalescing when they make the behavior clearer.

Example:

```ts
const displayName = user?.displayName ?? 'Unknown user';
```

### 5.4 Type Assertions

- Avoid type assertions when type narrowing can be used.
- Never use an assertion only to silence a compiler error.
- Validate external data before converting it to a domain type.

---

## 6. Functions and Control Flow

- Functions should have one responsibility.
- Keep functions short and easy to test.
- Declare explicit return types for exported functions and public APIs.
- Prefer early returns to deeply nested conditions.
- Avoid complex nested ternary expressions.
- Avoid mutating function arguments.

Example:

```ts
export function canEditTask(task: Task, userId: string): boolean {
  if (!task.assigneeId) {
    return false;
  }

  return task.assigneeId === userId;
}
```

---

## 7. Immutability and Data Updates

- Prefer `const` over `let`.
- Use immutable updates for application state.
- Do not mutate objects or arrays received from another module or component.
- Use `map`, `filter`, and `reduce` when they improve clarity; do not use them solely to avoid a simple loop.

Example:

```ts
const updatedTasks = tasks.map((task) =>
  task.id === taskId ? { ...task, status: 'DONE' } : task,
);
```

---

## 8. Asynchronous Code and Error Handling

- Prefer `async`/`await` for sequential asynchronous logic.
- Handle rejected promises at the appropriate boundary.
- Do not leave promises unhandled.
- Preserve the original error when rethrowing or logging.
- Return typed results from API clients.

Example:

```ts
async function loadBoard(boardId: string): Promise<Board> {
  const response = await boardApi.getBoard(boardId);
  return response.data;
}
```

Bad example:

```ts
loadBoard(boardId).catch(() => undefined);
```

---

## 9. API and External Data Boundaries

- Treat API responses, browser storage, URL parameters, and user input as untrusted data.
- Validate external data before using it as a domain object.
- Keep request and response DTOs separate from internal domain models when the contract differs.
- Do not expose internal errors, stack traces, tokens, or sensitive implementation details to users.
- Use a shared API client instead of duplicating request configuration.
- Define endpoint URLs in `src/shared/constants/api.ts`; make Axios calls
  only in feature `api/` files, keeping Java DTO and TypeScript fields in
  exact camelCase parity. Respect the approved success/error envelopes rather
  than inventing a frontend-only response shape.
- Keep decimal-valued money as strings or a decimal-safe type over the wire,
  not JavaScript `number`.

---

## 10. Logging and Sensitive Data

- Do not add `console.log` or invent a logging utility for feature code.
  Use the shared `notify` helper for client-safe user feedback and the
  established API error flow for failures.
- Never log passwords, access tokens, refresh tokens, cookies, payment information, or unnecessary personal data.
- Do not log an entire request or response when it may contain sensitive fields.

---

## 11. React and UI Rules

When using React:

- Keep components focused on one UI responsibility.
- Keep reusable business logic in hooks or service modules, not in large components.
- Use typed props and event handlers.
- Do not use array indexes as keys for reorderable or mutable lists.
- Keep loading, empty, error, and success states explicit.
- Avoid unnecessary state; derive values from existing state when possible.
- Do not perform side effects during render.
- Clean up subscriptions, timers, and event listeners in effects.
- Reuse shared components and externalize UI strings to VI/EN/KO resources;
  do not import `sonner` directly in a feature or inline a Zod schema inside
  a component.

Example:

```tsx
type TaskCardProps = {
  task: Task;
  onSelect: (taskId: string) => void;
};

export function TaskCard({ task, onSelect }: TaskCardProps) {
  return (
    <button type="button" onClick={() => onSelect(task.id)}>
      {task.title}
    </button>
  );
}
```

---

## 12. State Management

- Keep state close to the component or feature that owns it.
- Use a shared store only for state needed by multiple independent features.
- Define state and actions with explicit types.
- Avoid storing values that can be derived from other state.
- Keep server state management separate from local UI state.
- Use TanStack Query for server data, Zustand only for shared client state,
  and component/form state for local UI. Do not cache API responses in Zustand.

---

## 13. Security Rules

- Never hardcode secrets, API keys, or private tokens in source code.
- Do not inject unsanitized HTML into the DOM.
- Avoid `dangerouslySetInnerHTML` unless the content is trusted and sanitized.
- Validate and encode user-controlled values at the correct boundary.
- Do not rely on frontend checks for authorization; authorization must be enforced by the backend.

---

## 14. Comments and Documentation

- Write comments only when they explain intent, constraints, or non-obvious behavior.
- Do not add comments that simply repeat the code.
- Document exported functions, types, and public module contracts when their behavior is not self-evident.
- Keep comments accurate when code changes.

---

## 15. Testing Conventions

- Test observable behavior rather than implementation details.
- Cover successful, error, empty, and boundary cases where applicable.
- Use descriptive test names that state the scenario and expected result.
- Keep tests independent and deterministic.
- Colocate tests with the code under test; routed or query-backed tests use
  the shared `renderWithProviders`.
- Avoid weakening production types or behavior only to make tests pass.

Example:

```ts
describe('createTask', () => {
  it('creates a task with TODO status for a valid title', async () => {
    // arrange, act, assert
  });

  it('rejects an empty title', async () => {
    // arrange, act, assert
  });
});
```

---

## 16. Standard Summary

TypeScript source code in this project must follow these core standards:

- strict TypeScript configuration
- PascalCase for classes, interfaces, types, and enums
- lowerCamelCase for functions, methods, variables, and parameters
- UPPER_SNAKE_CASE for fixed module-level constants
- 2-space indentation and consistent formatter usage
- no unnecessary `any` or unsafe assertions
- explicit handling of null and undefined
- immutable state updates where practical
- typed and handled asynchronous operations
- validated external data
- no sensitive data in logs
- explicit UI states for loading, empty, error, and success
- behavior-focused tests

Following these rules keeps the TypeScript code consistent, type-safe, and easier to review, maintain, and extend.
