import json, sys

from box import Box


class SchedulerBase(object):

    @classmethod
    def check_stdin(klass):
        """
        Ensures that no arguments are passed in via the command line
        Need to make sure that if anything errors it takes it errors with a status code that is non-zero
        """

        if len(sys.argv) != 1:
            msg = f"must not pass any arguments to phenix scheduler: was passed {len(sys.argv) - 1}"

            klass.eprint(msg)
            klass.eprint("scheduler expects <executable> << <json_input>")

            sys.exit(1)


    @staticmethod
    def eprint(*args):
        """
        Prints errors to STDERR
        """

        print(*args, file=sys.stderr)


    def __init__(self, name):
        self.name = name

        self.check_stdin()

        # Keep this around just in case apps want direct access to it.
        self.raw_input = sys.stdin.read()

        # TODO: catch exceptions parsing JSON
        self.experiment = Box.from_json(self.raw_input)
