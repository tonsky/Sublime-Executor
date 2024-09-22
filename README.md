# Executor

Plugin that let you run any executable from your working dir inside Sublime Text.

![](./screenshots/commands.png)

![](./screenshots/run.png)

Simple plugin that walks your current working directories, finds all files marked as executable and let you run them inside Sublime Text.

Gives you these basic commands:

- Executor: Execute (`executor_execute`)
- Executor: Execute with Args (`executor_execute_with_args`)
- Executor: Execute Shell (`executor_execute_shell`)
- Executor: Repeat Recent (`executor_repeat_recent`)
- Executor: Repeat Last (`executor_repeat_last`)
- Executor: Cancel (`executor_cancel`)
- Executor: Clear Output (`executor_clear_output`)
- Executor: Toggle Bottom Group (`executor_toggle_bottom_group`)

Uses either `output.exec` panel or a view to stream both stdout and stderr.

Knows about `.gitignore` enough to skip looking into ignored paths.

Only one command can be run at the same time per window. Running second one will kill previous one.

## Installation

Look for “Executor” in Package Control.

Manually:

- Clone this repo into `~/Library/Application Support/Sublime Text/Packages`

## Running arbitrary shell command

Use `Executor: Execute Shell` command or add to your keybindings:

```
 {"keys":    ["ctrl+r"],
  "command": "executor_execute_shell",
  "args":    {"command": "clj -M -m user", "dir": "~/work/project"}},
```

`"dir"` is optional. If omitted, first open directory of current window is used.

## Auto-open panel on output

If you want Sublime to open output panel every time there’s new output, add this to the settings:

```
"executor_show_panel_on_output": true
```

## Outputting to view

Sometimes it’s desirable to redirect output to a real view which can be dragged to its own group or separated. Gives you more options for layout. For that, set

```
"executor_output_view": true
```

to open a scratch view for output instead of a panel (can be dragged etc).

Set

```
"executor_reuse_output_view": false
```

to create new view each time you execute a command (by default old view is reused).

Lastly, Executor has a command to quickly open/close a new group at the bottom of the window:

```
executor_toggle_bottom_group
```

When called without arguments, it will toggle the bottom group visibility. If passed `{"visible": true | false}`, it will act as open or close command.

You can change bottom group size by specifying

```
"executor_bottom_group_ratio": 0.25,
```

Output views are always opened in the last group of the window, so if you have one at the bottom, it’ll use it.

## Highlighting settings

You can set

```
"executor_file_regex": "^File "([^"]+)" line (\d+) col (\d+)",
"executor_base_dir": "<path>"
```

to make file names clickable in the output.

Optionally, also set

```
"executor_line_regex": "^\s+line (\d+) col (\d+)",
```

if line number information is printed on the next line.

You can also control wrapping:

```
"executor_word_wrap": true | false
```

These settings work both in global config and in project file `"settings"`.

## Known limitations

- Probably doesn’t work on Windows
- `.gitignore` only works with Git installed
- Sublime Text excludes are not supported
- On large projects without Git listing might take long time

## Credits

Made by [Niki Tonsky](https://twitter.com/nikitonsky).

## See also

[Writer Color Scheme](https://github.com/tonsky/sublime-scheme-writer): A color scheme optimized for long-form writing.

[Alabaster Color Scheme](https://github.com/tonsky/sublime-scheme-alabaster): Minimal color scheme for coding.

[Sublime Profiles](https://github.com/tonsky/sublime-profiles): Profile switcher.

[Clojure Sublimed](https://github.com/tonsky/clojure-sublimed):  Clojure support for Sublime Text 4.

## License

[MIT License](./LICENSE.txt)
