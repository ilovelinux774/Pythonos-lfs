"""Host-side unit tests for pysh — no root, no QEMU required.

    make unittest
    # or
    PYTHONPATH=system/usr/lib/pythonos:system/usr/lib \
        python3 -m unittest discover -s tests -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "system", "usr", "lib")
PKG = os.path.join(LIB, "pythonos")
# The repository also contains the hosted `pythonos` package. Keep the
# native image package first for these shell tests; otherwise its imports of
# pythonos.tui/pythonos.pysh would resolve to the hosted package.
# Running discovery from the repository puts the cwd in sys.path as `''`;
# remove both forms so the native package wins over the hosted package.
sys.path[:] = [entry for entry in sys.path if entry not in ("", ROOT)]
for entry in (PKG, LIB):
    if entry not in sys.path:
        sys.path.insert(0, entry)
# A preceding hosted-package test may have populated this namespace.
for module_name in list(sys.modules):
    if module_name == "pythonos" or module_name.startswith("pythonos."):
        del sys.modules[module_name]

from pysh.shell import Shell, expand_word, parse, tokenize  # noqa: E402


def run(command, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((PKG, LIB))
    env["TERM"] = "dumb"
    return subprocess.run(
        [sys.executable, "-m", "pysh.shell", "-c", command],
        capture_output=True, text=True, timeout=30, env=env, cwd=cwd or "/",
    )


class TokenizerTests(unittest.TestCase):
    def test_words_and_spaces(self):
        self.assertEqual(tokenize("echo hello   world"),
                         [("word", "echo"), ("word", "hello"), ("word", "world")])

    def test_quotes_are_preserved(self):
        toks = tokenize("echo 'a b' \"c d\"")
        self.assertEqual(toks, [("word", "echo"), ("word", "'a b'"), ("word", "\"c d\"")])

    def test_operators(self):
        toks = tokenize("a|b>c&&d")
        self.assertEqual([t for t in toks if t[0] == "op"],
                         [("op", "|"), ("op", ">"), ("op", "&&")])

    def test_redirect_fd_prefix_is_not_an_operator(self):
        toks = tokenize("echo a2>out")
        words = [v for k, v in toks if k == "word"]
        self.assertIn("a2", words)


class ParserTests(unittest.TestCase):
    def test_pipeline_segments(self):
        jobs = parse(tokenize("a | b | c"))
        self.assertEqual(len(jobs), 1)
        _connector, segments = jobs[0]
        self.assertEqual([[w for w in s.argv] for s in segments],
                         [["a"], ["b"], ["c"]])

    def test_connectors(self):
        jobs = parse(tokenize("a && b || c ; d"))
        self.assertEqual([c for c, _ in jobs], ["", "&&", "||", ";"])

    def test_redirects(self):
        _c, segments = parse(tokenize("echo hi > out.txt 2>&1"))[0]
        self.assertEqual(segments[0].stdout, "out.txt")
        self.assertTrue(segments[0].stderr_to_stdout)


class ExpansionTests(unittest.TestCase):
    env = {"HOME": "/root", "USER": "root", "X": "value", "__status__": "7"}

    def test_variables(self):
        self.assertEqual(expand_word("$USER", self.env), ["root"])
        self.assertEqual(expand_word("${X}", self.env), ["value"])
        self.assertEqual(expand_word("a$USER-b", self.env), ["aroot-b"])

    def test_status_variable(self):
        self.assertEqual(expand_word("$?", self.env), ["7"])

    def test_single_quotes_block_expansion(self):
        self.assertEqual(expand_word("'$USER'", self.env), ["$USER"])

    def test_double_quotes_allow_expansion(self):
        self.assertEqual(expand_word('"$USER"', self.env), ["root"])

    def test_tilde(self):
        self.assertEqual(expand_word("~/x", self.env), ["/root/x"])

    def test_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("g1.txt", "g2.txt"):
                open(os.path.join(tmp, name), "w").close()
            matches = expand_word(os.path.join(tmp, "*.txt"), self.env)
            self.assertEqual(len(matches), 2)


class ShellExecutionTests(unittest.TestCase):
    def test_echo(self):
        self.assertEqual(run("echo hello").stdout, "hello\n")

    @unittest.skipUnless(os.name == "posix", "native pysh pipelines require POSIX fork")
    def test_pipeline(self):
        proc = run("echo one | wc -l")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "1")

    def test_exit_status(self):
        self.assertIn("code=1", run("false; echo code=$?").stdout)

    def test_redirection_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.txt")
            run(f"echo payload > {path}")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "payload\n")

    def test_python_builtin(self):
        self.assertEqual(run("py 'print(21 * 2)'").stdout.strip(), "42")

    def test_command_not_found(self):
        proc = run("definitely-not-a-command")
        self.assertEqual(proc.returncode, 127)

    def test_chaining(self):
        out = run("true && echo yes").stdout
        self.assertIn("yes", out)
        out = run("false && echo no; echo after").stdout
        self.assertNotIn("no", out)
        self.assertIn("after", out)

    def test_files_builtins(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run(
                f"mkdir -p {tmp}/d && echo a > {tmp}/d/f && "
                f"cp {tmp}/d/f {tmp}/d/g && rm -r {tmp}/d && echo done")
            self.assertIn("done", proc.stdout)


class ShellObjectTests(unittest.TestCase):
    def test_aliases_expand(self):
        shell = Shell(interactive=False)
        shell.aliases["hi"] = "echo hello"
        captured = []
        original = sys.stdout
        try:
            import io
            sys.stdout = io.StringIO()
            shell.execute("hi")
            captured.append(sys.stdout.getvalue())
        finally:
            sys.stdout = original
        self.assertIn("hello", captured[0])

    def test_cd_updates_pwd(self):
        shell = Shell(interactive=False)
        start = os.getcwd()
        target = tempfile.gettempdir()
        try:
            shell.execute(f"cd {target}")
            self.assertEqual(os.path.normcase(os.getcwd()), os.path.normcase(target))
        finally:
            os.chdir(start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
