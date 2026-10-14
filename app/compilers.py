"""Compiler/build adapters.

An adapter turns a validated config into the argument list used to build
the program under test. It is the only place that knows compiler-specific
command-line conventions. To support another compiler, add an adapter
class here and register it in ``ADAPTERS`` - or use the ``generic``
adapter, which needs no code changes.
"""

import sys


class GnuCobolAdapter:
    """GnuCOBOL ``cobc``: ``<executable> <args...> -o <output> <source>``.

    The adapter owns ``-o`` and the source path, so they must not appear in
    the configured args.
    """

    name = "gnucobol"
    description = "GnuCOBOL (cobc). Output and source are appended as: -o <output> <source>"
    RESERVED = ("-o",)
    version_args = ["--version"]  # used only to record the compiler version in reports

    @classmethod
    def check_args(cls, args):
        errors = []
        for arg in args:
            if arg in cls.RESERVED or arg.startswith("-o"):
                errors.append("compiler.args: do not pass -o; the output path comes from the build directory setting")
        return errors

    @staticmethod
    def build_command(executable, args, source, output):
        return [executable, *args, "-o", str(output), str(source)]


class GenericAdapter:
    """Any compiler: args are used verbatim after placeholder substitution.

    An argument equal to ``{source}`` or ``{output}`` is replaced by the
    corresponding path. Substitution is whole-argument only, so a path with
    spaces always stays one argument. Example args for cobc:
    ``["-x", "-free", "-o", "{output}", "{source}"]``.
    """

    name = "generic"
    description = "Any compiler. Use {source} and {output} as whole arguments."
    version_args = None  # unknown convention: version is not collected

    @staticmethod
    def check_args(args):
        if "{source}" not in args:
            return ["compiler.args: the generic adapter needs a '{source}' argument"]
        return []

    @staticmethod
    def build_command(executable, args, source, output):
        mapping = {"{source}": str(source), "{output}": str(output)}
        return [executable, *(mapping.get(a, a) for a in args)]


ADAPTERS = {a.name: a for a in (GnuCobolAdapter, GenericAdapter)}


def executable_name(program_name):
    """File name of the built program for the current platform."""
    return program_name + (".exe" if sys.platform.startswith("win") else "")
