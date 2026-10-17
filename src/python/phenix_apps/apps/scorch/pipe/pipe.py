from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, StringConstraints

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.apps.scorch.app import MetadataBlock, Token
from phenix_apps.common.logger import logger


def _blank_is_unset(value: Any) -> Any:
    # an empty or blank string leaves the setting alone; any other wrong type
    # fails
    return None if isinstance(value, str) and not value.strip() else value


class PipeMetadata(MetadataBlock):
    """Metadata for the pipe component; see README.md for each field.

    A MetadataBlock, so unknown keys are warned about; no other component reads
    this block.
    """

    # spliced into minimega commands, which are joined with spaces
    pipe: Token
    # wrapped in single quotes for minimega; line breaks are refused as a
    # precaution (whether minimega keeps them inside one command is unverified)
    data: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^'\r\n]+$")]
        | None,
        BeforeValidator(_blank_is_unset),
    ] = None
    # a host command line; one line only
    via: Annotated[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, pattern=r"^[^\r\n]+$"),
            Field(strict=True),
        ]
        | None,
        BeforeValidator(_blank_is_unset),
    ] = None
    mode: Annotated[
        Literal["all", "round-robin", "random"] | None,
        BeforeValidator(_blank_is_unset),
    ] = None
    # None leaves the pipe's logging as it is
    log: bool | None = None


class Pipe(ComponentBase):
    """
    Implements minimega's "pipe" API.
    """

    metadata_model = PipeMetadata
    config: PipeMetadata

    def __init__(self):
        ComponentBase.__init__(self, "pipe")
        self.execute_stage()

    def start(self):
        logger.info(f"Starting user component: {self.name}")

        if self.config.via:
            logger.info(
                f"setting via '{self.config.via}' for pipe '{self.config.pipe}'"
            )
            self.mm.pipe_via(self.config.pipe, self.config.via)

        if self.config.mode:
            logger.info(
                f"setting mode '{self.config.mode}' for pipe '{self.config.pipe}'"
            )
            self.mm.pipe_mode(self.config.pipe, self.config.mode)

        if self.config.log is not None:
            state = "enabling" if self.config.log else "disabling"
            logger.info(f"{state} logging for pipe '{self.config.pipe}'")
            self.mm.pipe_log(self.config.pipe, str(self.config.log).lower())

        if self.config.data:
            logger.info(
                f"writing data '{self.config.data}' to pipe '{self.config.pipe}'"
            )
            self.mm.pipe(self.config.pipe, f"'{self.config.data}'")

        logger.info(f"Started user component: {self.name}")

    def cleanup(self):
        logger.info(f"Cleaning up user component: {self.name}")

        logger.info(f"clearing pipe '{self.config.pipe}'")
        self.mm.clear_pipe(self.config.pipe)

        logger.info(f"Cleaned up user component: {self.name}")


def main():
    Pipe()


if __name__ == "__main__":
    main()
