# Toolkit conventions

These rules apply throughout this repository.

## Purpose and implementation

- Toolkits are small, easy-to-read Bourne shell scripts for managing configuration
  and filesystem state. Keep operations direct and understandable.
- Use `#!/bin/sh` and Bourne/POSIX shell syntax. Avoid Bash-only features.
- Use `case` for argument decision trees that match one value against several
  options. Keep each branch expanded, with one operation per line.
- Use `if`/`elif`/`else` for conditions such as file checks and numeric comparisons.
- Write fixed sequences as explicit commands, not loops over hard-coded lists.
  Keep loops for variable arguments, file contents, and discovered files.
- Prefer one operation per line and direct command flow. Avoid callbacks and
  one-use helper functions when the steps are clearer written in place.
- Implement each command in its own script. Do not make shell commands wrappers
  around a Python, Node, or other application backend.
- Use ordinary command-line utilities for focused work, such as `flock` for
  locking and `age` for encryption. Do not reimplement specialized tools.
- Do not introduce databases, services, frameworks, or unnecessary abstractions.
  Existing code that does so is not a precedent for new work.

## Commands and shared helpers

- Use `mv`, `ls`, `rm`, `create`, `edit`, and `load` for the corresponding
  operations wherever they apply. Use `mv` for renames as well as moves.
- Follow the existing dispatcher layout: `src/<tool>` and `src/<tool>.bin/`.
  Top-level commands use `<tool>-<action>`; nested commands use directories and
  plain action filenames, such as `port.bin/allocate/pull`.
- Keep command logic in the command script. Extract only small, reusable shell
  functions into `src/lib/`, such as locking and atomic writes.
- Include concise `##<help>` blocks documenting usage and behavior.
- Keep output useful for shell composition: return requested values on stdout
  and errors on stderr, with meaningful exit statuses.

## Filesystem state

- Store persistent state beneath `$UTIL_PATH` using clear directory and file
  names. Keep state separate from installed commands and source files.
- Prefer simple text formats that shell utilities can read and update directly.
  State should be easy for a person to inspect; avoid serialization that forces
  commands to depend on a separate programming-language runtime.
- Create initial directories and files in the toolkit's `setup` script.
  Re-running setup must preserve existing configuration, keys, and allocations.
- Put shared validation and lock acquisition in `validate` before executing a
  command. Hold locks for the entire read/modify/write operation and release them
  on exit. Never delete an active lock file.
- Use the shared atomic-write helper when replacing state files. Preserve the
  original if generating replacement content fails.
- Never persist user passwords. Use restrictive permissions for sensitive state.

## Scope and verification

- Favor the smallest clear implementation that fulfills the request.
- Do not expand a focused change into a framework or unrelated rewrite.
- Check shell syntax with `sh -n`. Verify state-changing behavior in temporary
  directories, including failure and concurrency cases where relevant.
- Test tooling may use another language; shipped toolkit commands must remain
  shell implementations.
