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

Uses `output.exec` panel to stream both stdout and stderr.

Knows about `.gitignore` enough to skip looking into ignored paths.

Only one command can be run at the same time. Running second one will kill previous one.

## Installation

Look for “Executor” in Package Control after this is published.

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

## Settings

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

These settings work both in global config and in projet file `"settings"`.

## Known limitations

- Probably doesn’t work on Windows
- `!` in `.gitignore` is not supported
- Global `.gitignore` is not supported
- Sublime Text excludes are not supported
- On large projects listing might take long time

## Credits

Made by [Niki Tonsky](https://twitter.com/nikitonsky).

## See also

[Writer Color Scheme](https://github.com/tonsky/sublime-scheme-writer): A color scheme optimized for long-form writing.

[Alabaster Color Scheme](https://github.com/tonsky/sublime-scheme-alabaster): Minimal color scheme for coding.

[Sublime Profiles](https://github.com/tonsky/sublime-profiles): Profile switcher.

[Clojure Sublimed](https://github.com/tonsky/clojure-sublimed):  Clojure support for Sublime Text 4.

## License

[MIT License](./LICENSE.txt)
