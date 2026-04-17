import json
import sys
import traceback

from loguru import logger

import phenix_apps.common.settings as settings

PHENIX_JSON_LOG_CHUNK_SIZE = 16 * 1024


def _iter_log_chunks(text: str):
    """Yield line- and size-bounded chunks for transport-safe logging."""

    if text == "":
        yield ""
        return

    for line in text.splitlines():
        if line == "":
            yield ""
            continue

        for start in range(0, len(line), PHENIX_JSON_LOG_CHUNK_SIZE):
            yield line[start : start + PHENIX_JSON_LOG_CHUNK_SIZE]


def _iter_phenix_json_log_lines(message):
    """Yield newline-delimited JSON log lines for a loguru message.

    This helper function builds the JSON log entry by extracting relevant
    fields from the loguru record, adding traceback information for exceptions,
    and including any extra data bound to the logger.

    Args:
        message: The loguru message object.

    Yields:
        Individual JSON log lines, each terminated with a newline.
    """

    record = message.record

    # Core expects 'level' and 'msg' at the top level.
    base_entry = {
        "level": record["level"].name,
        "proc_time": record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "file": record["file"].name,
        "line": record["line"],
    }

    # Add any extra contextual kwargs passed to the logger (e.g. logger.bind(type="SCORCH").info("..."))
    if record["extra"]:
        base_entry.update(record["extra"])

    traceback_text = ""
    if record["exception"]:
        exc = record["exception"]
        traceback_text = "".join(traceback.format_exception(*exc))

    message_chunks = list(_iter_log_chunks(record["message"]))
    traceback_chunks = list(_iter_log_chunks(traceback_text)) if traceback_text else []

    if len(message_chunks) == 1 and len(traceback_chunks) <= 1:
        log_entry = dict(base_entry)
        log_entry["msg"] = message_chunks[0]
        if traceback_chunks:
            log_entry["traceback"] = traceback_chunks[0]
        yield json.dumps(log_entry) + "\n"
        return

    total_parts = len(message_chunks) + len(traceback_chunks)

    for part_num, chunk in enumerate(message_chunks, start=1):
        log_entry = dict(base_entry)
        log_entry["msg"] = chunk
        log_entry["part"] = part_num
        log_entry["parts"] = total_parts
        yield json.dumps(log_entry) + "\n"

    for part_num, chunk in enumerate(traceback_chunks, start=len(message_chunks) + 1):
        log_entry = dict(base_entry)
        log_entry["msg"] = chunk
        log_entry["part"] = part_num
        log_entry["parts"] = total_parts
        log_entry["chunk_type"] = "traceback"
        yield json.dumps(log_entry) + "\n"


def _format_phenix_json_log(message) -> str:
    """Formats a loguru message record into one or more flat JSON strings.

    This preserves the existing helper contract for callers and tests that need
    the full serialized payload as a single string.

    Args:
        message: The loguru message object.

    Returns:
        One or more newline-delimited JSON strings representing the log entry.
    """

    return "".join(_iter_phenix_json_log_lines(message))


def _write_phenix_json_log(stream, message) -> None:
    """Write each JSON frame as an individual flushed stream write.

    The Phenix core log reader is line-oriented. Emitting one frame at a time
    avoids bundling multiple JSON objects into a single stream write when a
    message is chunked across lines or size boundaries.
    """

    for log_line in _iter_phenix_json_log_lines(message):
        stream.write(log_line)
        stream.flush()


class PhenixFileSink:
    """A loguru sink that writes structured JSON logs to a file.

    This class implements a callable sink for `loguru`. It formats log records into
    a flat JSON schema and writes them to a specified file. This can be used for
    application-specific logging when not running under the phenix Core daemon.

    The file handle is kept open for the lifetime of the sink instance to
    improve performance by avoiding repeated file open/close operations for
    standalone logging.

    Attributes:
        _file: The open file handle for the log file.
    """

    def __init__(self, path: str):
        self._file = open(path, "a", encoding="utf-8")

    def __call__(self, message):
        _write_phenix_json_log(self._file, message)


def phenix_stderr_sink(message):
    """A loguru sink that writes structured JSON logs to stderr.

    This function is designed to be used as a sink with `loguru`. It takes a
    log message, formats it into the standard phenix JSON format using the
    `_format_phenix_json_log` helper, and writes the result to `sys.stderr`. This
    is the standard mechanism for inter-process communication (IPC) with the
    phenix Core daemon.

    Args:
        message: The loguru message object.
    """
    _write_phenix_json_log(sys.stderr, message)


def configure_logging(force_console: bool = False) -> None:
    """Configures the global loguru logger for phenix applications.

    This function sets up the logger based on environment variables and
    function arguments. It removes any existing handlers and adds a new one
    based on the following logic:

    1.  If `PHENIX_LOG_FILE` is "stderr" (and `force_console` is False),
        it configures the `phenix_stderr_sink` to write structured JSON
        logs to stderr. This is the standard for IPC with phenix Core.
    2.  If `PHENIX_LOG_FILE` is set to a file path (and `force_console` is
        False), it uses `PhenixFileSink` to write structured JSON logs to
        that file. This is useful for standalone app debugging.
    3.  Otherwise (or if `force_console` is True), it configures a
        human-readable, colored format to `sys.stderr`. This is useful for
        development and debugging.

    The log level is controlled by the `PHENIX_LOG_LEVEL` environment variable.

    Args:
        force_console: If True, forces human-readable output to the console,
            ignoring the `PHENIX_LOG_FILE` setting. Defaults to False.
    """
    logger.remove()

    log_level = settings.PHENIX_LOG_LEVEL.upper()
    log_file = settings.PHENIX_LOG_FILE

    if log_file == "stderr" and not force_console:
        # Write JSON directly to stderr for IPC with phenix Core.
        logger.add(
            phenix_stderr_sink,
            level=log_level,
        )
    elif log_file and not force_console:
        # File logging for standalone debugging.
        logger.add(
            PhenixFileSink(log_file),
            level=log_level,
            # Removed rotation="10 MB" because rotation is handled by the core app's lumberjack
        )
    else:
        # Console logging
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        )
