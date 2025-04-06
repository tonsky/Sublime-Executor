#!/usr/bin/env python
import sys
write = sys.stdout.write
for fg in [None, 39, 30, 90, 31, 91, 32, 92, 33, 93, 34, 94, 35, 95, 36, 96, 37, 97]:
  for bg in [None, 49, 40, 100, 41, 101, 42, 102, 43, 103, 44, 104, 45, 105, 46, 106, 47, 107]:
    if fg is None and bg is None:
      write("          ")
    elif fg is None:
      write("\33[%dm     %d  \33[m" % (bg, bg))
    elif bg is None:
      write("\33[%dm   %d     \33[m" % (fg, fg))
    else:
      write("\33[%d;%dm  %d %d  \33[m" % (fg, bg, fg, bg))
  write("\n")
