# Based on Default/exec.py

import codecs, collections, html, os, re, shutil, signal, subprocess, sys, threading, time
import sublime, sublime_plugin
from typing import Any, Dict, Tuple

ns = 'sublime-executor'

RE_REPLACE_GLOB = re.compile(r"\*\*|[\*\?\.\(\)\[\]\{\}\$\^\+\|]")

# Colors
FG_ANSI = {
  30: 'black',
  31: 'red',
  32: 'green',
  33: 'brown',
  34: 'blue',
  35: 'magenta',
  36: 'cyan',
  37: 'white',
  39: 'default',
  90: 'light_black',
  91: 'light_red',
  92: 'light_green',
  93: 'light_brown',
  94: 'light_blue',
  95: 'light_magenta',
  96: 'light_cyan',
  97: 'light_white'
}

BG_ANSI = {
    40: 'black',
    41: 'red',
    42: 'green',
    43: 'brown',
    44: 'blue',
    45: 'magenta',
    46: 'cyan',
    47: 'white',
    49: 'default',
    100: 'light_black',
    101: 'light_red',
    102: 'light_green',
    103: 'light_brown',
    104: 'light_blue',
    105: 'light_magenta',
    106: 'light_cyan',
    107: 'light_white'
}

RE_UNKNOWN_ESCAPES = re.compile(r"\x1b[^a-zA-Z]*[a-zA-Z]")
RE_COLOR_ESCAPES = re.compile(r"\x1b\[((?:;?\d+)*)m")

class State:
  def __init__(self):
    self.proc = None
    self.status = None
    self.next_cmd = None
    self.recents = []
    self.output_view = None
    self.region_id = 0

states = collections.defaultdict(lambda: State())

def get_state(window = None):
  if window is None:
    window = sublime.active_window()
  return states[window.id()]

def glob_to_re(s):
  def replace_glob(match):
    s = match.group(0)
    if s == "**":
      return ".*"
    elif s == "*":
      return "[^/]*"
    elif s == "?":
      return "[^/]"
    else:
      return "\\" + s
  pattern = RE_REPLACE_GLOB.sub(replace_glob, s)
  if pattern[0] != "/":
    pattern = "(^|/)" + pattern
  if pattern[-1] != "/":
    pattern = pattern + "($|/)"
  return re.compile(pattern)

def find_executables_impl(acc, folder, ignores):
  global find_start
  if time.time() - find_start > 0.2:
    return
  if os.path.exists(folder):
    local_ignores = ignores.copy()
    gitignore = os.path.join(folder, ".gitignore")
    if os.path.exists(gitignore):
      with open(gitignore, 'rt') as f:
        # https://git-scm.com/docs/gitignore
        for line in f.readlines():
          line = line.strip()
          if not line:
            pass
          elif line.startswith("#"):
            pass
          elif line.startswith("!"):
            pass # TODO negates the pattern; any matching file excluded by a previous pattern will become included again
          else:
            local_ignores.append(glob_to_re(line))
    for name in os.listdir(folder):
      path = os.path.join(folder, name)
      matches = [p.pattern for p in local_ignores if re.search(p, path)]
      if matches:
        # print("Ignoring %s because of %s" % (path, matches))
        pass
      elif os.path.isfile(path):
        if os.access(path, os.X_OK):
          acc.append(path)
          # print(path)
      elif os.path.isdir(path):
        find_executables_impl(acc, path, local_ignores)

def find_executables(window):
  global find_start
  find_start = time.time()
  results = []
  for folder in window.folders():
    head, tail = os.path.split(folder)
    executables = []
    find_executables_impl(executables, folder, [re.compile("(^|/)\\.git($|/)")])
    for e in executables:
      results.append({"name": e[len(head) + 1:], "cmd": "./" + os.path.basename(e), "cwd": os.path.dirname(e)})
  return results

def run_command(window, cmd, args):
  state = get_state(window)
  if state.proc:
    state.next_cmd = (cmd, args)
    state.proc.kill()
  else:
    window.run_command(cmd, args)

def refresh_status(view):
  if view:
    state = get_state(view.window())
    if state.status:
      view.set_status(ns, state.status)
    else:
      view.erase_status(ns)

def set_status(s, view):
  if view:
    state = get_state(view.window())
    state.status = s
    refresh_status(view)

class ExecutorEventListener(sublime_plugin.EventListener):
  def on_activated_async(self, view):
    refresh_status(view)

  def on_pre_close_window(self, window):
    state = get_state(window)
    if state.proc:
      state.proc.kill()
    else:
      del states[window.id()]

class ArgsInputHandler(sublime_plugin.TextInputHandler):
  def placeholder(self):
    return 'Additional arguments'

class SelectExecutableInputHandler(sublime_plugin.ListInputHandler):
  def __init__(self, window, args):
    start = time.perf_counter()
    self.executables = find_executables(window)
    self.args = args
    # print("found %i items in %f ms" % (len(self.executables), (time.perf_counter() - start) * 1000))

  def placeholder(self):
    return 'Select executable to run'

  def list_items(self):
    if self.executables:
        return [(cmd["name"], cmd) for cmd in self.executables]
    else:
        return [("No executables found", False)]

  def next_input(self, args):
    return ArgsInputHandler() if self.args else None

class ProcessListener:
    def on_data(self, proc, data):
        pass

    def on_finished(self, proc):
        pass


class AsyncProcess:
    """
    Encapsulates subprocess.Popen, forwarding stdout to a supplied
    ProcessListener (on a separate thread)
    """

    def __init__(self, cmd, shell_cmd, env, listener, path="", shell=False):
        """ "path" and "shell" are options in build systems """

        if not shell_cmd and not cmd:
            raise ValueError("shell_cmd or cmd is required")

        if shell_cmd and not isinstance(shell_cmd, str):
            raise ValueError("shell_cmd must be a string")

        self.shell_cmd = shell_cmd
        self.listener = listener
        self.killed = False

        self.start_time = time.time()

        # Hide the console window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Set temporary PATH to locate executable in cmd
        if path:
            old_path = os.environ["PATH"]
            # The user decides in the build system whether he wants to append
            # $PATH or tuck it at the front: "$PATH;C:\\new\\path",
            # "C:\\new\\path;$PATH"
            os.environ["PATH"] = os.path.expandvars(path)

        proc_env = os.environ.copy()
        proc_env.update(env)
        for k, v in proc_env.items():
            proc_env[k] = os.path.expandvars(v)

        settings = sublime.load_settings("Preferences.sublime-settings")
        proc_env["TERM_PROGRAM"] = "Sublime-Executor"
        if "TERM" not in proc_env:
          proc_env["TERM"] = settings.get("executor_unix_term", "linux")
        if "LANG" not in proc_env:
          proc_env["LANG"] = settings.get("executor_unix_lang", "en_US.UTF-8")

        if sys.platform == "win32":
            preexec_fn = None
        else:
            preexec_fn = os.setsid

        if shell_cmd:
            if sys.platform == "win32":
                # Use shell=True on Windows, so shell_cmd is passed through
                # with the correct escaping
                cmd = shell_cmd
                shell = True
            elif sys.platform == "darwin":
                # Use a login shell on OSX, otherwise the users expected env
                # vars won't be setup
                cmd = ["/usr/bin/env", "bash", "-l", "-c", shell_cmd]
                shell = False
            elif sys.platform == "linux":
                # Explicitly use /bin/bash on Linux, to keep Linux and OSX as
                # similar as possible. A login shell is explicitly not used for
                # linux, as it's not required
                cmd = ["/usr/bin/env", "bash", "-c", shell_cmd]
                shell = False

        self.proc = subprocess.Popen(
            cmd,
            bufsize=0,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            startupinfo=startupinfo,
            env=proc_env,
            preexec_fn=preexec_fn,
            shell=shell)

        if path:
            os.environ["PATH"] = old_path

        self.stdout_thread = threading.Thread(
            target=self.read_fileno,
            args=(self.proc.stdout, True)
        )

    def start(self):
        self.stdout_thread.start()

    def kill(self):
        if not self.killed:
            print("[ Executor ] Killing " + self.shell_cmd)
            self.killed = True
            if sys.platform == "win32":
                # terminate would not kill process opened by the shell cmd.exe,
                # it will only kill cmd.exe leaving the child running
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    "taskkill /PID %d /T /F" % self.proc.pid,
                    startupinfo=startupinfo)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.terminate()

    def poll(self):
        return self.proc.poll() is None

    def exit_code(self):
        return self.proc.poll()

    def read_fileno(self, file, execute_finished):
        decoder = \
            codecs.getincrementaldecoder(self.listener.encoding)('replace')

        while True:
            data = decoder.decode(file.read(2**16))
            data = data.replace('\r\n', '\n').replace('\r', '\n')

            if len(data) > 0 and not self.killed:
                self.listener.on_data(self, data)
            else:
                if execute_finished:
                    self.listener.on_finished(self)
                break

class CommandInputHandler(sublime_plugin.TextInputHandler):
  def placeholder(self):
    return 'Shell command to run'

class ExecutorExecuteShellCommand(sublime_plugin.WindowCommand):
    def run(self, command, dir = None):
        window = self.window
        if dir:
            dir = os.path.abspath(os.path.expandvars(os.path.expanduser(dir)))
        elif len(window.folders()) > 0:
            dir = window.folders()[0]
        elif (view := window.active_view()) and (file := view.file_name()):
            dir = os.path.dirname(file)
        else:
            dir = os.path.expanduser("~")
        cmd = {"name": command,
               "cmd": command,
               "cwd": dir}
        run_command(window, "executor_impl", {"select_executable": cmd, "args": []})

    def input(self, args):
        if "command" not in args:
            return CommandInputHandler()

class ExecutorImplCommand(sublime_plugin.WindowCommand, ProcessListener):
    OUTPUT_LIMIT = 2 ** 27

    def __init__(self, window):
        super().__init__(window)
        self.errs_by_file = {}
        self.annotation_sets_by_buffer = {}
        self.show_errors_inline = True

    def settings(self):
        return sublime.load_settings("Preferences.sublime-settings")

    def use_output_view(self):
        settings = self.settings()
        return settings.get("executor_output_view", False)

    def get_output_view(self):
        window = self.window
        state = get_state(window)
        output_view = state.output_view
        use_output_view = self.use_output_view()
        if output_view is None or not output_view.is_valid() or ((output_view.element() is None) != use_output_view):
            if use_output_view:
                active_group = window.active_group()
                active_view = window.active_view()
                output_view = window.new_file()
                output_view.set_scratch(True)
                group = window.num_groups() - 1
                index = len(window.views_in_group(group))
                window.set_view_index(output_view, group, index)
                self.init_output_view(output_view)
                window.focus_group(active_group)
                window.focus_view(active_view)
            else:
                output_view = window.find_output_panel('exec') or window.create_output_panel('exec')
            state.output_view = output_view
        return output_view

    def init_output_view(self, view):
        state = get_state(self.window)
        settings = view.settings()
        settings.set("result_file_regex", self.file_regex)
        settings.set("result_line_regex", self.line_regex)
        settings.set("result_base_dir", self.working_dir)
        settings.set("word_wrap", self.word_wrap)
        settings.set("line_numbers", False)
        settings.set("gutter", False)
        settings.set("scroll_past_end", False)
        settings.set("color_scheme", "auto")
        settings.set("dark_color_scheme", "Executor Dark.hidden-color-scheme")
        settings.set("light_color_scheme", "Executor Light.hidden-color-scheme")


        view.assign_syntax(self.syntax)
        if self.use_output_view():
            view.set_name("▶️ [ RUN ] " + self.name)
        else:
            # Call create_output_panel a second time after assigning the above
            # settings, so that it'll be picked up as a result buffer
            self.window.create_output_panel("exec")

    def run(self,
            select_executable,
            args,
            file_regex="",
            line_regex="",
            encoding="utf-8",
            env={},
            quiet=False,
            kill_previous=False,
            update_annotations_only=False,
            word_wrap=None,
            syntax="Packages/Text/Plain text.tmLanguage",
            # Catches "path" and "shell"
            **kwargs):

        if update_annotations_only:
            if self.show_errors_inline:
                self.update_annotations()
            return

        state = get_state(self.window)
        state.command = self

        if kill_previous and state.proc:
            state.proc.kill()

        name = select_executable["name"] + (" " + args if args else "")
        self.name = name
        shell_cmd = select_executable["cmd"] + (" " + args if args else "")
        self.shell_cmd = shell_cmd
        working_dir = select_executable.get("cwd")
        cmd = {"name": name,
               "cmd": shell_cmd,
               "cwd": working_dir}
        if cmd in state.recents:
          state.recents.remove(cmd)
        state.recents.insert(0, cmd)

        settings = self.window.active_view().settings()
        show_panel_on_build = settings.get("show_panel_on_build", True)
        reuse_output_view = settings.get("executor_reuse_output_view", True)

        self.file_regex = file_regex or settings.get("executor_file_regex", "")
        self.line_regex = line_regex or settings.get("executor_line_regex", "")
        self.working_dir = settings.get("executor_base_dir", working_dir)
        self.word_wrap = word_wrap if word_wrap is not None else settings.get("executor_word_wrap", True)
        self.syntax = syntax

        # Default the to the current files directory if no working directory
        # was given
        if (working_dir == "" and
                self.window.active_view() and
                self.window.active_view().file_name()):
            working_dir = os.path.dirname(self.window.active_view().file_name())

        
        # Try not to call get_output_panel until the regexes are assigned
        if not reuse_output_view:
            state.output_view = None
        state.output_view = self.get_output_view()
        state.output_view.run_command("executor_clear_output_impl")
        self.init_output_view(state.output_view)

        self.encoding = encoding
        self.quiet = quiet

        state.proc = None
        if not self.quiet:
            if shell_cmd:
                print("[ Executor ] Running " + shell_cmd)
            elif cmd:
                cmd_string = cmd
                if not isinstance(cmd, str):
                    cmd_string = " ".join(cmd)
                print("[ Executor ] Running " + cmd_string)
            sublime.status_message("Building")

        if show_panel_on_build:
            if self.use_output_view():
                group, index = self.window.get_view_index(state.output_view)
                # print(f"group {group} index {index} active view {self.window.active_view_in_group(group)} output_view {state.output_view}")
                if self.window.active_view_in_group(group) != state.output_view:
                    self.window.focus_view(state.output_view)
            else:
                self.window.run_command("executor_show_panel", {"panel": "output.exec"})

        self.hide_annotations()
        self.show_errors_inline = settings.get("show_errors_inline", True)

        merged_env = env.copy()
        if self.window.active_view():
            user_env = self.window.active_view().settings().get('build_env')
            if user_env:
                merged_env.update(user_env)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if working_dir != "":
            os.chdir(working_dir)

        self.output_size = 0
        self.should_update_annotations = False

        self.write("[ RUN ] \"%s\" in %s\n" % (shell_cmd, working_dir))
        max_len = 50
        cmd_name = cmd["name"] if len(cmd["name"]) <= max_len + 3 else cmd["name"][:max_len] + "..."
        set_status("▶️ " + cmd_name, self.window.active_view())

        try:
            # Forward kwargs to AsyncProcess
            state.proc = AsyncProcess(cmd, shell_cmd, merged_env, self, **kwargs)
            state.proc.start()

        except Exception as e:
            self.write(str(e) + "\n")
            if not self.quiet:
                self.write("[ EXCEPTION ]\n")
            set_status(None, window.active_view())

    def write(self, characters):
        if self.window.active_view().settings().get("executor_show_panel_on_output", False):
            self.window.run_command("executor_show_panel", {"panel": "output.exec"})

        state = states[self.window.id()]
        view = self.get_output_view()

        decolorized = ""
        original_pos = 0
        decolorized_pos = 0
        fg = "default"
        bg = "default"
        regions = []
        def iteration(start, end, group):
            nonlocal decolorized, original_pos, decolorized_pos, fg, bg, regions
            text = characters[original_pos:start]
            text = RE_UNKNOWN_ESCAPES.sub("", text)
            decolorized += text
            if len(text) > 0 and (fg != "default" or bg != "default"):
                regions.append({"text":  text,
                                "start": decolorized_pos,
                                "end":   decolorized_pos + len(text),
                                "fg":    fg,
                                "bg":    bg})
            digits = re.findall(r"\d+", group) or ["0"]
            for digit in digits:
                digit = int(digit)
                if digit in FG_ANSI:
                    fg = FG_ANSI[digit]
                if digit in BG_ANSI:
                    bg = BG_ANSI[digit]
                if digit == 0:
                    fg = 'default'
                    bg = 'default'
            original_pos = end
            decolorized_pos += len(text)

        for m in RE_COLOR_ESCAPES.finditer(characters):
            iteration(m.start(), m.end(), m.group(1))
        iteration(len(characters), len(characters), "")

        insertion_point = view.size()
        view.run_command('append', {'characters': decolorized, 'force': True, 'scroll_to_end': True})
        
        for region in regions:
            fg = region['fg']
            bg = region['bg']
            scope = f'executor.{ fg }.{ bg }'
            start = insertion_point + region['start']
            end = insertion_point + region['end']
            state.region_id += 1
            view.add_regions("executor#{}".format(state.region_id), [sublime.Region(start, end)], scope)

        # Updating annotations is expensive, so batch it to the main thread
        def annotations_check():
            errs = self.get_output_view().find_all_results_with_text()
            errs_by_file = {}
            for file, line, column, text in errs:
                if file not in errs_by_file:
                    errs_by_file[file] = []
                errs_by_file[file].append((line, column, text))
            self.errs_by_file = errs_by_file

            self.update_annotations()

            self.should_update_annotations = False

        if not self.should_update_annotations:
            if self.show_errors_inline and characters.find('\n') >= 0:
                self.should_update_annotations = True
                sublime.set_timeout(lambda: annotations_check())

    def on_data(self, _proc, data):
        # Truncate past the limit
        if self.output_size >= self.OUTPUT_LIMIT:
            return

        self.write(data)
        self.output_size += len(data)

        if self.output_size >= self.OUTPUT_LIMIT:
            self.write('[Output Truncated]\n')

    def on_finished(self, proc):
        status = None
        print("[ Executor ] Finished " + proc.shell_cmd)
        if proc.killed:
            status = "CANCEL"
            self.write("[ CANCEL ]\n")
        elif not self.quiet:
            elapsed = time.time() - proc.start_time
            if elapsed < 1:
                elapsed_str = "%.0fms" % (elapsed * 1000)
            else:
                elapsed_str = "%.1fs" % (elapsed)

            exit_code = proc.exit_code()
            if exit_code == 0 or exit_code is None:
                status = "DONE"
                self.write("[ DONE ] in %s\n" % elapsed_str)
            else:
                status = "FAIL"
                self.write("[ FAIL ] with code %d in %s\n" % (exit_code, elapsed_str))

        if not self.window.is_valid():
          del states[self.window.id()]
        else:
          set_status(None, self.window.active_view())
          state = get_state(self.window)
          state.proc = None
          if self.use_output_view():
            self.get_output_view().set_name("[ %s ] %s" % (status, self.name))
          if cmd := state.next_cmd:
            (cmd, args) = cmd
            state.next_cmd = None
            self.window.run_command(cmd, args)

    def update_annotations(self):
        stylesheet = '''
            <style>
                #annotation-error {
                    background-color: color(var(--background) blend(#fff 95%));
                }
                html.dark #annotation-error {
                    background-color: color(var(--background) blend(#fff 95%));
                }
                html.light #annotation-error {
                    background-color: color(var(--background) blend(#000 85%));
                }
                a {
                    text-decoration: inherit;
                }
            </style>
        '''

        for file, errs in self.errs_by_file.items():
            view = self.window.find_open_file(file)
            if view:
                selection_set = []
                content_set = []

                line_err_set = []

                for line, column, text in errs:
                    pt = view.text_point(line - 1, column - 1)
                    if (line_err_set and
                            line == line_err_set[len(line_err_set) - 1][0]):
                        line_err_set[len(line_err_set) - 1][1] += (
                            "<br>" + html.escape(text, quote=False))
                    else:
                        pt_b = pt + 1
                        if view.classify(pt) & sublime.CLASS_WORD_START:
                            pt_b = view.find_by_class(
                                pt,
                                forward=True,
                                classes=(sublime.CLASS_WORD_END))
                        if pt_b <= pt:
                            pt_b = pt + 1
                        selection_set.append(
                            sublime.Region(pt, pt_b))
                        line_err_set.append(
                            [line, html.escape(text, quote=False)])

                for text in line_err_set:
                    content_set.append(
                        '<body>' + stylesheet +
                        '<div class="error" id=annotation-error>' +
                        '<span class="content">' + text[1] + '</span></div>' +
                        '</body>')

                view.add_regions(
                    "exec",
                    selection_set,
                    scope="invalid",
                    annotations=content_set,
                    flags=(sublime.DRAW_SQUIGGLY_UNDERLINE |
                           sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE),
                    on_close=self.hide_annotations)

    def hide_annotations(self):
        for window in sublime.windows():
            for file, errs in self.errs_by_file.items():
                view = window.find_open_file(file)
                if view:
                    view.erase_regions("exec")
                    view.hide_popup()

        view = sublime.active_window().active_view()
        if view:
            view.erase_regions("exec")
            view.hide_popup()

        self.errs_by_file = {}
        self.annotation_sets_by_buffer = {}
        self.show_errors_inline = False

class ExecutorExecuteWithArgsCommand(sublime_plugin.WindowCommand):
  def run(self, select_executable, args):
    if select_executable:
        run_command(self.window, "executor_impl", {"select_executable": select_executable, "args": args})

  def input(self, args):
      return SelectExecutableInputHandler(self.window, True)

class ExecutorExecuteCommand(sublime_plugin.WindowCommand):
  def run(self, select_executable):
    if select_executable:
        run_command(self.window, "executor_impl", {"select_executable": select_executable, "args": ""})

  def input(self, args):
    return SelectExecutableInputHandler(self.window, False)

class SelectRecentInputHandler(sublime_plugin.ListInputHandler):
  def placeholder(self):
    return 'Select executable to run'

  def list_items(self):
    state = get_state()
    return [(cmd["name"], cmd) for cmd in state.recents]

class ExecutorRepeatRecentCommand(sublime_plugin.WindowCommand):
  def run(self, select_recent):
    run_command(self.window, "executor_impl", {"select_executable": select_recent, "args": ""})

  def input(self, args):
    return SelectRecentInputHandler()

  def is_enabled(self):
    state = get_state()
    return bool(state.recents)

class ExecutorRepeatLastCommand(sublime_plugin.WindowCommand):
  def run(self):
    state = get_state(self.window)
    run_command(self.window, "executor_impl", {"select_executable": state.recents[0], "args": ""})

  def is_enabled(self):
    state = get_state(self.window)
    return len(state.recents) >= 1

class ExecutorCancelCommand(sublime_plugin.WindowCommand):
  def run(self):
    state = get_state(self.window)
    if state.proc:
      state.proc.kill()

  def is_enabled(self):
    state = get_state(self.window)
    return state.proc != None 

class ExecutorClearOutputImplCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    state = get_state(self.view.window())
    state.command.hide_annotations()
    self.view.erase(edit, sublime.Region(0, self.view.size()))

class ExecutorClearOutputCommand(sublime_plugin.WindowCommand):
  def run(self):
    state = get_state(self.window)
    state.output_view.run_command("executor_clear_output_impl")
  
  def is_enabled(self):
    state = get_state(self.window)
    return bool(state.output_view)

class ExecutorToggleBottomGroupCommand(sublime_plugin.WindowCommand):
  def run(self, visible = None):
    window = self.window
    layout = window.layout()
    cols = len(layout['cols'])
    rows = len(layout['rows'])
    is_visible = rows > 2 and layout['cells'][-1] == [0, rows - 2, cols - 1, rows - 1]
    active_group = window.active_group()
    active_view = window.active_view()
    if is_visible and visible != True:
       # hide
       coeff = layout['rows'][-2]
       new_rows = [(row / coeff) for row in (layout['rows'][:-1])]
       new_cells = layout['cells'][:-1]
       window.set_layout({'cells': new_cells, 'rows': new_rows, 'cols': layout['cols']})
       window.focus_group(active_group)
       window.focus_view(active_view)
    elif not is_visible and visible != False:
       # show
       settings = sublime.load_settings("Preferences.sublime-settings")
       coeff = 1.0 - settings.get('executor_bottom_group_ratio', 0.33)
       new_rows = [row * coeff for row in layout['rows']] + [1.0]
       new_cells = layout['cells'] + [[0, rows - 1, cols - 1, rows]]
       window.set_layout({'cells': new_cells, 'rows': new_rows, 'cols': layout['cols']})
       window.focus_group(active_group)
       window.focus_view(active_view)

class ExecutorShowPanelCommand(sublime_plugin.WindowCommand):
  def run(self, panel, extra_lines = None):
    window = self.window
    window.run_command('show_panel', {'panel': panel})

    for i in range(window.num_groups()):
      if view := window.active_view_in_group(i):
        if extra_lines is None:
          settings = view.settings()
          extra_lines = settings.get("executor_show_panel_extra_lines", 2)

        if sel := view.sel():
          cursor = max(r.end() for r in sel)
          cursor_layout_x, cursor_layout_y = view.text_to_layout(cursor)
          viewport_x, viewport_y = view.viewport_position()
          _, viewport_h = view.viewport_extent()
          line_h = view.line_height()
          if cursor_layout_y - viewport_y > viewport_h - 8 - line_h * (extra_lines + 1):
            view.set_viewport_position((viewport_x, cursor_layout_y + line_h * (extra_lines + 1) - viewport_h))

def plugin_unloaded():
  for state in states.values():
    if state.proc:
      state.proc.kill()
