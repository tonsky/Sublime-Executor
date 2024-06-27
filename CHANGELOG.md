### 1.5.0 - Jun 27, 2024

- Added `executor_show_panel_on_output` option

### 1.4.1 - Feb 6, 2024

- Don’t throw if there are no files/no directories #6

### 1.4 - Jan 30, 2024

- Support colored output
- Better escape sequences filter

### 1.3 - Dec 28, 2023

Ability to redirect output to a view.

New settings:

- `executor_output_view`
- `executor_reuse_output_view`
- `executor_bottom_group_ratio`

New commands:

- `executor_toggle_bottom_group`

Fixed:

- `executor_file_regex`
- `executor_base_dir`
- `executor_line_regex`
- `executor_word_wrap`

### 1.2.2 - Nov 30, 2023

- Fixed exceptions

### 1.2.1 - Nov 30, 2023

- `executor_clear_output`

### 1.2.0 - Nov 30, 2023

- Executions are per-window

### 1.1.6 - Oct 17, 2023

- Don’t die if project has non-existing folders

### 1.1.5 - Aug 19, 2023

- Allow running any command on top of another one, implicitly killing previous one

### 1.1.4 - Aug 19, 2023

- Kill running process on exit

### 1.1.3 - Aug 9, 2023

- Strip away escape sequences

### 1.1.2 - Aug 7, 2023

- Better gitignore matching

### 1.1.1 - Apr 10, 2023

- Typo #4

### 1.1.0 - Apr 3, 2023

- Execute Shell #4
- executor_repeat_last will now automatically stop current process if present

### 1.0.5 - Jan 5, 2023

- Redid process management based on Default/exec.py

### 1.0.4 - Dec 6, 2022

- Display running status in status bar #2

### 1.0.3 - Oct 8, 2022

- Reliable Ctrl+C

### 1.0.2 - Aug 23, 2022

- Allow setting `executor_file_regex`, `executor_line_regex`, `executor_base_dir` and `executor_wrap`

### 1.0.1 - Aug 12, 2022

- prefix all commands with `executor_`

### 1.0.0 - Aug 12, 2022

- Initial