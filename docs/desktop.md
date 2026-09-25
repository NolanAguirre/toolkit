# Configurable development desktop

The `desktop` toolkit opens named project entries on specific GNOME workspaces.
Your five existing projects have been imported, and your enabled login startup
entry now uses `desktop start --login`.

```sh
desktop start                    # launch the saved layout
desktop start --dry-run          # inspect commands without executing them
desktop start harness            # launch only Harness
desktop workspace ls
desktop command ls harness
```

Log out and back in after the initial extension install or an extension update.
Full desktop placement requires GNOME 46 and fixed workspaces. Workspace numbers
are one-based. The launcher checks that the configured workspaces exist; it does
not change your desktop settings.

## Add or change a workspace

```sh
desktop workspace create my-project 3 "$HOME/personal/my-project"
desktop workspace edit harness 2 "$HOME/personal/harness"
desktop workspace mv my-project new-name
desktop workspace rm new-name
```

`edit` changes the workspace number and directory while preserving commands.
Multiple project entries may use the same desktop workspace. `rm` removes only
configuration; it does not delete repositories or close running applications.
Entries launch in name order; their assigned workspace numbers determine placement.

## Add commands

```sh
desktop command create my-project 10-service tab 'make start'
desktop command create my-project 20-shell tab ':'
desktop command create my-project 25-tests tab 'npm run test:watch'
desktop command create my-project 30-cursor cursor 'cursor --new-window .'
desktop command create my-project 40-browser brave 'brave-browser --new-window http://localhost:7000/'
```

Create the workspace before adding commands. Single-quote command text to keep
variables, pipes, and redirections from executing in your current terminal.
Commands run in the workspace's configured directory. Command scripts use POSIX
shell syntax and are launched through your interactive `$SHELL` (Bash by default),
so your normal shell initialization, including nvm, is available.

| Kind | Behavior |
| --- | --- |
| `tab` | One terminal tab; all tabs in the entry share a new GNOME Terminal window |
| `cursor` | Launch command and place the next new Cursor window |
| `brave` | Launch command and place the next new Brave window |
| `window:<application-class>` | Place another application's new window, matching its class/application ID (case insensitive substring) |
| `background` | Run without a terminal; log output, with no window placement |

Names sort alphabetically. Prefix them with `10-`, `20-`, etc. to control order.
Terminal tabs launch together first, followed by other commands in name order.
A tab stays open as an interactive shell after its command finishes. `:` opens a
plain shell. Window commands must request a **new** window, since existing windows
are excluded from placement. Avoid manually opening windows of the same app while
startup is running; the helper places the next new matching window.

## Edit, reorder, move, or remove commands

```sh
desktop command edit harness 10-service 'make start'
EDITOR=nano desktop command edit harness 40-browser
desktop command mv harness 25-tests harness 15-tests
desktop command mv harness 15-tests my-project 15-tests
desktop command rm my-project 15-tests
```

The optional command text replaces the script. Without it, `edit` uses `$EDITOR`
(default `vi`; one executable name). Invalid shell syntax and failed editor saves
leave the original intact. To change a command's kind, remove and recreate it.
When S6 Craft gains a Makefile, change its `10-service` command to `make start`.

Imported browser commands include a bounded `curl` wait before opening the URL.
Edit the browser script to change the URL in both the wait and the launch command.
You can use any shell logic in a command, including environment variables, pipes,
or a different start command. New browser commands have no implicit readiness wait.

## Startup, repeated runs, and state

```sh
desktop autostart create         # enable after desktop login
desktop autostart rm             # disable
desktop start --force harness    # deliberately launch Harness again
```

Autostart saves the installed command path and current `$UTIL_PATH`; you do not
need to export it in GNOME's login environment. It waits up to 60 seconds for the
extension. It cannot open windows before you log in.

Repeated starts skip successfully placed windows and submitted background commands
in the current login. Added non-tab commands can launch on the next invocation.
New or edited terminal tabs need a new terminal window: close the old service
window first, then use `--force <workspace>`, or wait until the next login.
`--force` starts all commands in the selected entry again, including services.
Editing configuration does not move or stop already running windows or processes.
If an application opened but placement failed, close that window before retrying.
A launched command is not a service health check; errors remain in the tab or log.

Persistent configuration lives at `$UTIL_PATH/desktop/workspaces/<name>`:

- `config`: workspace number on line 1, absolute working directory on line 2.
- `commands/<command-name>/kind`: command kind.
- `commands/<command-name>/run`: editable shell script.

Use the management commands for locking, validation, and atomic writes. Configuration
is separate from installed scripts and survives rebuilds and repeated setup. Back
up `$UTIL_PATH/desktop` to preserve it. Each launch snapshots commands under
`$XDG_RUNTIME_DIR/toolkit-desktop/<session>/`; logs and duplicate-launch markers are
there too. Runtime state is cleared when the login runtime directory is removed.

## Installation and verification

```sh
toolkit build
toolkit setup desktop
desktop install
# Log out and back in to load the GNOME extension.
```

New installations start with empty configuration. Setup preserves existing entries.
The launcher is POSIX shell; the small GNOME extension is JavaScript because GNOME
Wayland controls workspace placement through its shell. It exposes only bounded
window-placement operations over the session bus, with a 45-second timeout.

```sh
toolkit test desktop
python3 /home/nolan/personal/toolkit/tests/desktop.py
```

Verification covers help, syntax, isolated configuration changes, concurrent creates,
failed-edit preservation, autostart, mocked launch arguments and duplicate handling.
Live window placement and service startup still need checking after a new login.
