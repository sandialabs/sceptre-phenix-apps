"""Metadata model and password derivation for the harden app."""

import hashlib
import string
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from phenix_apps.common.metadata import Hostname, MetadataBlock

# Account names safe unquoted in a shell.
Username = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,31}$")]
# Local Windows account names (at most 20 characters), safe single-quoted in PowerShell.
WindowsUsername = Annotated[
    str, Field(pattern=r"^[A-Za-z]([A-Za-z0-9._ -]{0,18}[A-Za-z0-9._-])?$")
]
# Potential passwords must be printable ASCII.
Password = Annotated[str, Field(min_length=8, max_length=127, pattern=r"^[ -~]+$")]
Seed = Annotated[str, Field(min_length=8, max_length=256, pattern=r"^[ -~]+$")]
Autologon = Literal["keep", "disable"]

# Accounts the OS will not let go of
LINUX_BUILTIN: Final[str] = "root"
WINDOWS_BUILTIN: Final[str] = "administrator"

GENERATED_LENGTH: Final[int] = 16
_UPPER: Final[str] = string.ascii_uppercase
_LOWER: Final[str] = string.ascii_lowercase
_DIGITS: Final[str] = string.digits
_SYMBOLS: Final[str] = "!-"
_ALPHABET: Final[str] = _UPPER + _LOWER + _DIGITS + _SYMBOLS
# The first four bytes each pick from one class, so every generated password has all four and passes a Windows complexity policy.
_CLASSES: Final[tuple[str, ...]] = (_UPPER, _LOWER, _DIGITS, _SYMBOLS)


def derive_password(seed: str, hostname: str, username: str) -> str:
    """The deterministic password for an account: SHA-256 of
    ``<seed>/<hostname>/<username>``, one character per digest byte."""

    digest = hashlib.sha256(f"{seed}/{hostname}/{username}".encode()).digest()
    chars = []

    for i, byte in enumerate(digest[:GENERATED_LENGTH]):
        alphabet = _CLASSES[i] if i < len(_CLASSES) else _ALPHABET
        chars.append(alphabet[byte % len(alphabet)])

    return "".join(chars)


def meets_windows_policy(password: str, username: str) -> bool:
    """The default Windows complexity policy: three of four character classes
    and not the account name. A rejected password would leave the account on
    the image's password with nothing to report it."""

    classes = (
        any(c.isupper() for c in password),
        any(c.islower() for c in password),
        any(c.isdigit() for c in password),
        any(c in string.punctuation for c in password),
    )
    contains_name = len(username) >= 3 and username.lower() in password.lower()
    return sum(classes) >= 3 and not contains_name


class UserSpec(MetadataBlock):
    """What to do with one account: set a literal password or a generated one."""

    password: Password | None = None
    generate: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> "UserSpec":
        if (self.password is None) == (not self.generate):
            raise ValueError("set exactly one of 'password' and 'generate: true'")
        return self


class SshSpec(MetadataBlock):
    root_login: Literal["unchanged", "prohibit-password", "no"] = "unchanged"
    empty_passwords: Literal["unchanged", "no"] = "unchanged"


class LinuxSpec(MetadataBlock):
    """The Linux block, and the shape of a Linux host's own metadata."""

    users: dict[Username, UserSpec] = Field(default_factory=dict)
    remove_users: list[Username] = Field(default_factory=list)
    ssh: SshSpec = SshSpec()

    @model_validator(mode="after")
    def _removable(self) -> "LinuxSpec":
        _check_removals(self.users, self.remove_users, LINUX_BUILTIN)
        return self


class WindowsSpec(MetadataBlock):
    """The Windows block, and the shape of a Windows host's own metadata."""

    users: dict[WindowsUsername, UserSpec] = Field(default_factory=dict)
    remove_users: list[WindowsUsername] = Field(default_factory=list)
    autologon: Autologon = "keep"

    @model_validator(mode="after")
    def _accounts(self) -> "WindowsSpec":
        _check_removals(self.users, self.remove_users, WINDOWS_BUILTIN)
        for name, user in self.users.items():
            if user.password and not meets_windows_policy(user.password, name):
                raise ValueError(
                    f"users.{name}.password: needs three of upper case, lower "
                    "case, digits and symbols, and must not contain the account name"
                )
        return self


def _check_removals(
    users: dict[str, UserSpec], remove_users: list[str], builtin: str
) -> None:
    for name in remove_users:
        if name.lower() == builtin:
            raise ValueError(
                f"remove_users: '{name}' is built in and cannot be removed"
            )
        if name in users:
            raise ValueError(f"remove_users: '{name}' is also in users")


class HardenMetadata(MetadataBlock):
    seed: Seed | None = None
    exclude: list[Hostname] = Field(default_factory=list)
    linux: LinuxSpec = LinuxSpec()
    windows: WindowsSpec = WindowsSpec()
