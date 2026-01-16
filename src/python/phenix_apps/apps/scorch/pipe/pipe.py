from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common.logger import logger

import sys


class Pipe(ComponentBase):
    """
    Implements minimega's "pipe" API.
    """

    def __init__(self):
        ComponentBase.__init__(self, "pipe")
        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        pipe = self.metadata.get("pipe", None)
        data = self.metadata.get("data", None)
        via = self.metadata.get("via", None)
        mode = self.metadata.get("mode", None)
        log = self.metadata.get("log", None)

        if not pipe:
            self.eprint("pipe not specified but is required")
            sys.exit(1)

        if via:
            self.print(f"setting via '{via}' for pipe '{pipe}'")
            self.mm.pipe_via(pipe, via)

        if mode:
            if mode not in ["all", "round-robin", "random"]:
                self.eprint(
                    f"mode invalid: {mode} - options are all|round-robin|random"
                )
                sys.exit(1)
            self.print(f"setting mode '{mode}' for pipe '{pipe}'")
            self.mm.pipe_mode(pipe, mode)

        if log is not None:
            if log is True:
                self.print(f"enabling logging for pipe '{pipe}'")
            elif log is False:
                self.print(f"disabling logging for pipe '{pipe}'")
            else:
                self.eprint(f"log setting invalid: {log} - options are true|false")
                sys.exit(1)
            self.mm.pipe_log(pipe, str(log).lower())

        if data:
            self.print(f"writing data '{data}' to pipe '{pipe}'")
            self.mm.pipe(pipe, f"'{data}'")

        logger.info(f"Started user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        pipe = self.metadata.get("pipe", None)

        if not pipe:
            self.eprint("pipe not specified but is required")
            sys.exit(1)

        self.print(f"clearing pipe '{pipe}'")
        self.mm.clear_pipe(pipe)

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Pipe()


if __name__ == "__main__":
    main()
