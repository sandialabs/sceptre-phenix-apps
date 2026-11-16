"""Pydantic metadata validation shared by apps and SCORCH components."""

import difflib
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from phenix_apps.common import utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger

# Metadata rules. Values are validated in pydantic's strict mode: a wrong type
# (the string "false" for a bool, "6" for an int) or a malformed value fails the
# stage, even in a field that is not used yet, so a config is either valid or
# rejected up front. Only an unknown key in a MetadataBlock, usually a typo, is
# a warning, logged with a did-you-mean hint.


def _hostname(value: str) -> str:
    try:
        return utils.validate_hostname(value)
    except AppError:
        raise ValueError(
            "not a valid hostname: 2 to 63 letters, digits and interior hyphens"
        ) from None


# Field types for metadata models. Names, interfaces and paths are interpolated
# into commands (minimega joins its arguments with spaces, treats `#` as a
# comment and `\` as an escape), so a Token is one word of plain characters:
# none of those, quotes, or shell syntax. Every sink of a Token today takes an
# argument vector (minimega's `shell`, miniccc, ovs-vsctl), so the allowlist is
# defense in depth, and it still holds `vm[1-3]`, `a,b` and `ns//vlan`.
# Args is free text for a command line that a shell may parse (inside a
# `bash -c '...'`, where minimega's lexer has already turned a backslash-n
# into a newline), so it is plain characters too: no quotes, backslashes or
# shell syntax. FilterExpr is for text that only ever reaches a program as
# arguments, never a shell: it also takes the `( ) [ ] ! & | < > ^` of a
# tcpdump filter. An empty Args or FilterExpr is valid.
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][\w.-]*$")]
Token = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+,=@/\[\]-]+$")]
Args = Annotated[str, Field(pattern=r"^[A-Za-z0-9_ .,:=@%/+-]*$")]
FilterExpr = Annotated[str, Field(pattern=r"^[A-Za-z0-9_ .,:=@%/+*()\[\]!&|<>^-]*$")]
# A topology node name, by phenix core's rules (utils.validate_hostname).
Hostname = Annotated[str, AfterValidator(_hostname)]
# A Linux interface name: at most 15 characters (IFNAMSIZ), no `/`, `:` or
# whitespace. phenix's schema leaves interface names unconstrained.
Interface = Annotated[str, Field(pattern=r"^[A-Za-z0-9_][\w.-]{0,14}$")]
# A file path on a Linux or Windows VM, with forward slashes (Windows accepts
# them; minimega would eat a backslash). No shell or cmd.exe metacharacters, so
# it is safe unquoted in `rm`, `del` or a minimega file command.
FilePath = Annotated[str, Field(pattern=r"^(?:[A-Za-z]:)?[\w./+@-]+$")]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class MetadataBlock(BaseModel):
    """A nested metadata block. Unknown keys are kept but warned about, since
    they are usually typos the old code silently ignored."""

    model_config = ConfigDict(extra="allow")


def _unknown_keys(model: BaseModel, path: str = "") -> list[str]:
    """Warnings for unknown keys in every MetadataBlock below model."""

    prefix = f"{path}." if path else ""
    found = []
    if isinstance(model, MetadataBlock):
        known = list(type(model).model_fields)
        for key in model.model_extra or {}:
            close = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
            hint = (
                f"did you mean '{close[0]}'?" if close else "known: " + ", ".join(known)
            )
            found.append(
                f"{prefix}{key}: unknown key, ignored. Fix: remove it ({hint})"
            )

    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            found += _unknown_keys(value, f"{prefix}{name}")
        elif isinstance(value, list | dict):
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for label, item in items:
                if isinstance(item, BaseModel):
                    found += _unknown_keys(item, f"{prefix}{name}.{label}")
    return found


def validate_metadata[M: BaseModel](
    model: type[M],
    metadata: dict[str, Any] | None,
    name: str,
    kind: str = "component",
) -> tuple[M, list[str]]:
    """Validate the metadata of a component or app, returning the model and
    its warnings.

    Raises one ValueError listing every fatal problem. Field values are left
    out of messages so nothing sensitive reaches the status file or logs.
    """

    try:
        config = model.model_validate({} if metadata is None else metadata, strict=True)
    except ValidationError as ex:
        problems = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc']) or '(metadata)'}: {err['msg']}"
            for err in ex.errors()
        )
        raise ValueError(
            f"invalid metadata for {kind} '{name}' "
            f"({ex.error_count()} problem(s)):\n{problems}"
        ) from None
    return config, _unknown_keys(config)


def parse_metadata[M: BaseModel](
    model: type[M],
    metadata: dict[str, Any] | None,
    name: str,
    kind: str = "component",
) -> M:
    """validate_metadata, logging each warning against the component or app."""

    config, warnings = validate_metadata(model, metadata, name, kind)
    for message in warnings:
        logger.warning(f"metadata warning for {kind} '{name}': {message}")
    return config
