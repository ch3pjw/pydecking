from __future__ import print_function

import blessings


class Terminal(blessings.Terminal):
    def print_step(self, title, *lines):
        print("----->", self.green(title))
        for line in lines:
            self.print_line(line)

    @staticmethod
    def print_line(*line):
        print("      ", *line)

    def print_error_line(self, *line):
        print(self.red(' !    '), *line)

    def print_error(self, title, *lines):
        print("----->", self.red(title))
        for line in lines:
            self.print_error_line(line)

    def print_warning_line(self, *line):
        print(self.yellow(' !    '), *line)

    def print_warning(self, title, *lines):
        print("----->", self.yellow(title))
        for line in lines:
            self.print_warning_line(line)

term = Terminal()
