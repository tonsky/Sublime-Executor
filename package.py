# Based on Default/exec.py

import codecs, os, re, shutil, signal, subprocess, sys, threading, time
import sublime, sublime_plugin
from typing import Any, Dict, Tuple

ns = 'sublime-executor'

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
  pattern = re.sub(r"\*\*|[\*\?\.\(\)\[\]\{\}\$\^\+\|]", replace_glob, s)
  if pattern[0] != "/":
    pattern = "(^|/)" + pattern
  if pattern[-1] != "/":
    pattern = pattern + "($|/)"
  return re.compile(pattern)

def find_executables_impl(acc, folder, ignores):
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
  results = []
  for folder in window.folders():
    head, tail = os.path.split(folder)
    executables = []
    find_executables_impl(executables, folder, [re.compile("(^|/)\\.git($|/)")])
    for e in executables:
      results.append({"name": e[len(head) + 1:], "cmd": "./" + os.path.basename(e), "cwd": os.path.dirname(e)})
  return results

def refresh_status(view):
  global status
  if view:
    if status:
      view.set_status(ns, status)
    else:
      view.erase_status(ns)

def set_status(s, view):
  global status
  status = s
  refresh_status(view)

class ExecutorEventListener(sublime_plugin.EventListener):
    def on_activated_async(self, view):
        refresh_status(view)

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
    return [(cmd["name"], cmd) for cmd in self.executables]

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
        else:
            dir = window.folders()[0]
        cmd = {"name": command,
               "cmd": command,
               "cwd": dir}
        window.run_command("executor_execute_with_args", {"select_executable": cmd, "args": []})

    def input(self, args):
        return CommandInputHandler()

class ExecutorExecuteWithArgsCommand(sublime_plugin.WindowCommand, ProcessListener):
    OUTPUT_LIMIT = 2 ** 27

    def __init__(self, window):
        super().__init__(window)

        self.errs_by_file = {}
        self.annotation_sets_by_buffer = {}
        self.show_errors_inline = True
        self.output_view = None

    def run(self,
            select_executable,
            args,
            file_regex="",
            line_regex="",
            encoding="utf-8",
            env={},
            quiet=False,
            kill=False,
            kill_previous=False,
            update_annotations_only=False,
            word_wrap=True,
            syntax="Packages/Text/Plain text.tmLanguage",
            # Catches "path" and "shell"
            **kwargs):

        if update_annotations_only:
            if self.show_errors_inline:
                self.update_annotations()
            return

        global proc
        if kill:
            if proc:
                proc.kill()
            return

        if kill_previous and proc and proc.poll():
            proc.kill()

        global recents
        name = select_executable["name"] + (" " + args if args else "")
        shell_cmd = select_executable["cmd"] + (" " + args if args else "")
        working_dir = select_executable.get("cwd")
        cmd = {"name": name,
               "cmd": shell_cmd,
               "cwd": working_dir}
        if cmd in recents:
          recents.remove(cmd)
        recents.insert(0, cmd)

        if self.output_view is None:
            # Try not to call get_output_panel until the regexes are assigned
            self.output_view = self.window.create_output_panel("exec")

        # Default the to the current files directory if no working directory
        # was given
        if (working_dir == "" and
                self.window.active_view() and
                self.window.active_view().file_name()):
            working_dir = os.path.dirname(self.window.active_view().file_name())

        self.output_view.settings().set("result_file_regex", file_regex)
        self.output_view.settings().set("result_line_regex", line_regex)
        self.output_view.settings().set("result_base_dir", working_dir)
        self.output_view.settings().set("word_wrap", word_wrap)
        self.output_view.settings().set("line_numbers", False)
        self.output_view.settings().set("gutter", False)
        self.output_view.settings().set("scroll_past_end", False)
        self.output_view.assign_syntax(syntax)

        # Call create_output_panel a second time after assigning the above
        # settings, so that it'll be picked up as a result buffer
        self.window.create_output_panel("exec")

        self.encoding = encoding
        self.quiet = quiet

        proc = None
        if not self.quiet:
            if shell_cmd:
                print("Running " + shell_cmd)
            elif cmd:
                cmd_string = cmd
                if not isinstance(cmd, str):
                    cmd_string = " ".join(cmd)
                print("Running " + cmd_string)
            sublime.status_message("Building")

        preferences_settings = \
            sublime.load_settings("Preferences.sublime-settings")
        show_panel_on_build = \
            preferences_settings.get("show_panel_on_build", True)
        if show_panel_on_build:
            self.window.run_command("show_panel", {"panel": "output.exec"})

        self.hide_annotations()
        self.show_errors_inline = \
            preferences_settings.get("show_errors_inline", True)

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
        set_status("▶️ " + cmd["name"], self.window.active_view())

        try:
            # Forward kwargs to AsyncProcess
            proc = AsyncProcess(cmd, shell_cmd, merged_env, self, **kwargs)
            proc.start()

        except Exception as e:
            self.write(str(e) + "\n")
            if not self.quiet:
                self.write("[ EXCEPTION ]\n")
            set_status(None, window.active_view())

    def input(self, args):
      return SelectExecutableInputHandler(self.window, True)

    def is_enabled(self, kill=False, **kwargs):
        global proc
        return proc is None

    def write(self, characters):
        characters = re.sub(r"\x1b\[[^m]*m", "", characters)
        self.output_view.run_command(
            'append',
            {'characters': characters, 'force': True, 'scroll_to_end': True})

        # Updating annotations is expensive, so batch it to the main thread
        def annotations_check():
            errs = self.output_view.find_all_results_with_text()
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

    def on_finished(self, _proc):
        global proc, next_cmd

        if proc.killed:
            self.write("[ CANCEL ]\n")
        elif not self.quiet:
            elapsed = time.time() - proc.start_time
            if elapsed < 1:
                elapsed_str = "%.0fms" % (elapsed * 1000)
            else:
                elapsed_str = "%.1fs" % (elapsed)

            exit_code = proc.exit_code()
            if exit_code == 0 or exit_code is None:
                self.write("[ DONE ] in %s\n" % elapsed_str)
            else:
                self.write("[ FAIL ] with code %d in %s\n" % (exit_code, elapsed_str))

        set_status(None, self.window.active_view())
        proc = None
        if cmd := next_cmd:
          next_cmd = None
          self.window.run_command(cmd)

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

class ExecutorExecuteCommand(sublime_plugin.WindowCommand):
  def run(self, select_executable):
    self.window.run_command("executor_execute_with_args", {"select_executable": select_executable, "args": ""})

  def input(self, args):
    return SelectExecutableInputHandler(self.window, False)

  def is_enabled(self):
    return proc == None

class SelectRecentInputHandler(sublime_plugin.ListInputHandler):
  def placeholder(self):
    return 'Select executable to run'

  def list_items(self):
    global recents
    return [(cmd["name"], cmd) for cmd in recents]

class ExecutorRepeatRecentCommand(sublime_plugin.WindowCommand):
  def run(self, select_recent):
    self.window.run_command("executor_execute_with_args", {"select_executable": select_recent, "args": ""})

  def input(self, args):
    return SelectRecentInputHandler()

  def is_enabled(self):
    global proc, recents
    return proc == None and bool(recents)

class ExecutorRepeatLastCommand(sublime_plugin.WindowCommand):
  def run(self):
    global proc, recents, next_cmd
    if proc:
      next_cmd = "executor_repeat_last"
      proc.kill()
    else:
      self.window.run_command("executor_execute_with_args", {"select_executable": recents[0], "args": ""})

  def is_enabled(self):
    global proc, recents
    return len(recents) >= 1

class ExecutorCancelCommand(sublime_plugin.WindowCommand):
  def run(self):
    global proc
    if proc:
      proc.kill()

  def is_enabled(self):
    return proc != None 

def plugin_loaded():
  global proc, recents, status, next_cmd
  proc = None
  recents = []
  status = None
  next_cmd = None
  # recents.append({"name": "skija/script/build.py --skia-dir ~/ws/skia-build/skia",
  #                 "cmd":  "./build.py --skia-dir ~/ws/skia-build/skia",
  #                 "cwd":  "/Users/tonsky/ws/skija/script"})
  # recents.append({"name": "skija/script/clean.py",
  #                 "cmd":  "./clean.py",
  #                 "cwd":  "/Users/tonsky/ws/skija/script"})
  # recents.append({"name": "skija/script/build.py",
  #                 "cmd":  "./build.py",
  #                 "cwd":  "/Users/tonsky/ws/skija/script"})

def plugin_unloaded():
  global proc
  if proc:
    proc.kill()
