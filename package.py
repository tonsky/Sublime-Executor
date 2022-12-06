import os, re, shutil, signal, sublime, sublime_plugin, subprocess, threading, time
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
  return pattern

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
    matches = [p for p in local_ignores if re.search(p, path)]
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
    find_executables_impl(executables, folder, ["\\.git"])
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

def execute(window, cmd):
  def report(s, end = "\n"):
    global output
    output.run_command('append', {'characters': s + end, 'force': True, 'scroll_to_end': True})
  
  global proc, output
  start = time.perf_counter()

  if output is None:
    # Try not to call get_output_panel until the regexes are assigned
    output = window.create_output_panel("exec")

  settings = window.active_view().settings()
  output.settings().set("result_file_regex", settings.get("executor_file_regex", ""))
  output.settings().set("result_line_regex", settings.get("executor_line_regex", ""))
  output.settings().set("result_base_dir", settings.get("executor_base_dir", ""))
  output.settings().set("word_wrap", settings.get("executor_wrap", True))
  output.settings().set("line_numbers", False)
  output.settings().set("gutter", False)
  output.settings().set("scroll_past_end", False)
  # Call create_output_panel a second time after assigning the above
  # settings, so that it'll be picked up as a result buffer
  window.create_output_panel("exec")
  window.run_command("show_panel", {"panel": "output.exec"})
  
  report("[ RUN ] \"%s\" in %s" % (cmd["cmd"], cmd.get("cwd")))
  set_status("▶️ " + cmd["name"], window.active_view())
  with subprocess.Popen(cmd["cmd"],
                        bufsize=1,
                        cwd=cmd.get("cwd"),
                        shell=True,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        preexec_fn=os.setsid,
                        text=True) as p:
    proc = p
    try:
      for line in p.stdout:
        report(line, end="")
    except:
      pass

  set_status(None, window.active_view())

  elapsed = time.perf_counter() - start
  if elapsed < 1:
      elapsed_str = "%.0f ms" % (elapsed * 1000)
  else:
      elapsed_str = "%.1f s" % (elapsed)

  if proc:
    if proc.poll() == 0:
      report("[ DONE ] in %s" % elapsed_str)
    else:
      report("[ FAIL ] with code %i in %s" % (proc.poll(), elapsed_str))
    proc = None
  else:
    report("[ CANCEL ] after %s" % elapsed_str)

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

class ExecutorExecuteWithArgsCommand(sublime_plugin.WindowCommand):
  def run(self, select_executable, args):
    # print("RunWithArgs", select_executable, type(select_executable), args, type(args))
    global recents
    cmd = {"name": select_executable["name"] + (" " + args if args else ""),
           "cmd":  select_executable["cmd"] + (" " + args if args else ""),
           "cwd":  select_executable.get("cwd")}
    if cmd in recents:
      recents.remove(cmd)
    recents.insert(0, cmd)
    threading.Thread(daemon=True, target=execute, args=(self.window, cmd)).start()

  def input(self, args):
    return SelectExecutableInputHandler(self.window, True)

  def is_enabled(self):
    return proc == None

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
    global recents
    self.window.run_command("executor_execute_with_args", {"select_executable": recents[0], "args": ""})

  def is_enabled(self):
    global proc, recents
    return proc == None and len(recents) >= 1

class ExecutorCancelCommand(sublime_plugin.WindowCommand):
  def run(self):
    global proc
    if proc:
      os.killpg(proc.pid, signal.SIGTERM)
      proc.terminate()
      proc = None

  def is_enabled(self):
    return proc != None 

def plugin_loaded():
  global proc, recents, output, status
  proc = None
  recents = []
  output = None
  status = None
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
    proc.communicate()
    proc = None
