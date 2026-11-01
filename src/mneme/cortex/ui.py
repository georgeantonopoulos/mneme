"""Small terminal drawing kit for the Mneme CLI: colour, boxes, steps, menus and a progress line.

No dependencies. Colour and in-place updates switch off when output is not a terminal or ``NO_COLOR`` is
set, and box drawing falls back to ASCII when the terminal cannot encode it.
"""
from __future__ import annotations

import os
import shutil
import sys
import time

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36"}


class UI:
    def __init__(self, stream=None, *, color: bool | None = None, interactive: bool | None = None):
        self.out = stream or sys.stdout
        tty = hasattr(self.out, "isatty") and self.out.isatty()
        self.color = tty and not os.environ.get("NO_COLOR") if color is None else color
        self.interactive = (tty and sys.stdin.isatty()) if interactive is None else interactive
        encoding = (getattr(self.out, "encoding", None) or "").lower()
        self.fancy = "utf" in encoding
        self._progress_open = False

    # -- text ---------------------------------------------------------------------------------
    def style(self, text: str, *names: str) -> str:
        if not self.color or not names:
            return text
        return f"\033[{';'.join(_CODES[n] for n in names)}m{text}\033[0m"

    def glyph(self, fancy: str, plain: str) -> str:
        return fancy if self.fancy else plain

    def say(self, text: str = "") -> None:
        self._end_progress()
        print(text, file=self.out, flush=True)

    def ok(self, text: str) -> None:
        self.say(f"  {self.style(self.glyph('✓', '+'), 'green', 'bold')} {text}")

    def warn(self, text: str) -> None:
        self.say(f"  {self.style('!', 'yellow', 'bold')} {text}")

    def fail(self, text: str) -> None:
        self.say(f"  {self.style(self.glyph('✗', 'x'), 'red', 'bold')} {text}")

    def note(self, text: str) -> None:
        self.say(f"    {self.style(text, 'dim')}")

    # -- structure ----------------------------------------------------------------------------
    def banner(self, title: str, subtitle: str = "") -> None:
        tl, tr, bl, br, h, v = (self.glyph(c, p) for c, p in
                                (("╭", "+"), ("╮", "+"), ("╰", "+"), ("╯", "+"), ("─", "-"), ("│", "|")))
        mark = self.glyph("◉", "*")
        inner = f" {mark} {title}" + (f"  {subtitle}" if subtitle else "")
        width = max(len(inner) + 2, 44)
        self.say()
        self.say("  " + self.style(tl + h * width + tr, "cyan"))
        padded = inner.ljust(width)
        styled = padded.replace(title, self.style(title, "bold"), 1).replace(mark, self.style(mark, "cyan", "bold"), 1)
        if subtitle:
            styled = styled.replace(subtitle, self.style(subtitle, "dim"), 1)
        self.say("  " + self.style(v, "cyan") + styled + self.style(v, "cyan"))
        self.say("  " + self.style(bl + h * width + br, "cyan"))

    def step(self, number: int, total: int, title: str) -> None:
        line = self.glyph("──", "--")
        self.say()
        self.say(f"  {self.style(f'{number}/{total}', 'cyan', 'bold')} {self.style(line, 'dim')} {self.style(title, 'bold')}")

    def table(self, rows: list[tuple[str, str]]) -> None:
        width = max((len(k) for k, _ in rows), default=0)
        for key, value in rows:
            self.say(f"    {self.style(key.ljust(width), 'dim')}  {value}")

    def card(self, header: str, body: str, *, accent: str = "cyan") -> None:
        bar = self.style(self.glyph("│", "|"), accent)
        self.say(f"  {bar} {header}")
        cols = shutil.get_terminal_size((100, 20)).columns - 6
        for line in _wrap(body, max(cols, 40)):
            self.say(f"  {bar} {self.style(line, 'dim')}")

    # -- input --------------------------------------------------------------------------------
    def ask(self, prompt: str, default: str = "") -> str:
        hint = f" {self.style(f'[{default}]', 'dim')}" if default else ""
        self._end_progress()
        try:
            answer = input(f"  {self.style('?', 'cyan', 'bold')} {prompt}{hint} ").strip()
        except EOFError:
            answer = ""
        return answer or default

    def confirm(self, prompt: str, default: bool = True) -> bool:
        answer = self.ask(prompt + (" (Y/n)" if default else " (y/N)")).lower()
        return default if not answer else answer.startswith("y")

    def choose(self, prompt: str, options: list[tuple[str, str]], default: int = 0) -> int:
        """Numbered menu of ``(label, description)``; returns the chosen index."""
        self.say(f"  {self.style('?', 'cyan', 'bold')} {prompt}")
        width = max(len(label) for label, _ in options)
        for i, (label, desc) in enumerate(options):
            marker = self.style(self.glyph("›", ">"), "cyan", "bold") if i == default else " "
            text = self.style(label.ljust(width), "bold") if i == default else label.ljust(width)
            self.say(f"   {marker} {self.style(str(i + 1), 'cyan')}  {text}" + (f"  {self.style(desc, 'dim')}" if desc else ""))
        while True:
            raw = self.ask("Choose", str(default + 1))
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
            self.warn(f"Type a number from 1 to {len(options)}.")

    # -- progress -----------------------------------------------------------------------------
    def progress(self, label: str, done: int, total: int) -> None:
        if not self.interactive:
            if done == total:
                self.say(f"  {self.style(self.glyph('•', '-'), 'cyan')} {label} {self.style(f'{done}/{total}', 'dim')}")
            return
        width = 24
        filled = int(width * done / total) if total else width
        bar = self.glyph("█", "#") * filled + self.glyph("░", ".") * (width - filled)
        spin = self.glyph("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "|/-\\")[int(time.time() * 8) % (10 if self.fancy else 4)]
        line = f"\r  {self.style(spin, 'cyan')} {label.ljust(26)} {self.style(bar, 'cyan')} {done}/{total}"
        self.out.write(line + "\033[K")
        self.out.flush()
        self._progress_open = True
        if done == total:
            self._end_progress()

    def _end_progress(self) -> None:
        if self._progress_open:
            self.out.write("\n")
            self.out.flush()
            self._progress_open = False


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words, line = paragraph.split(), ""
        for word in words:
            if line and len(line) + 1 + len(word) > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
    return [line for line in lines if line] or [""]
