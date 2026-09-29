"""Execution-owned CC state on minimega's shared namespace connection.

Minimega stores filter and prefix on the namespace, not on each socket. The
advisory file lock covers applying both settings and one submission; response
polling happens after the lock is released. All managed Scorch processes must
use the same control directory on the experiment controller.
"""

import fcntl
import hashlib
import os
from pathlib import Path


class ScopedCC:
    def __init__(self, connection, namespace: str, execution: str, directory: str):
        self._connection = connection
        self._owned_prefix = f"scorch-{execution}-"
        self._filter = None
        self._prefix = ""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256(namespace.encode()).hexdigest()
        self._lock_path = root / f"cc-{digest}.lock"

    def __getattr__(self, name):
        method = getattr(self._connection, name)
        if not callable(method) or not name.startswith(("cc_", "clear_cc_")):
            return method

        def call(*args, **kwargs):
            if name == "cc_filter":
                if args or kwargs:
                    self._filter = args[0] if args else kwargs.get("filter")
                    return []
            elif name == "cc_prefix":
                if args or kwargs:
                    self._prefix = (args[0] if args else kwargs.get("prefix")) or ""
                    return []
            elif name == "clear_cc_filter":
                self._filter = None
                return []
            elif name == "clear_cc_prefix":
                self._prefix = ""
                return []

            # Separate open descriptions also serialize threads/connections in
            # the same process. Never unlink the lock file on release.
            fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    mm = self._connection
                    mm.clear_cc_filter()
                    if self._filter:
                        mm.cc_filter(self._filter)
                    mm.cc_prefix(self._owned_prefix + self._prefix)
                    if name in ("clear_cc_commands", "clear_cc_responses"):
                        return self._delete_owned(mm, "all", name.endswith("commands"))
                    if name in ("cc_delete_command", "cc_delete_response"):
                        target = args[0] if args else kwargs.get("id", "all")
                        return self._delete_owned(
                            mm, str(target), name == "cc_delete_command"
                        )
                    if name == "cc_responses":
                        target = str(args[0] if args else kwargs.get("id", "all"))
                        if target == "all":
                            results = []
                            for prefix in self._owned_prefixes(mm):
                                results.extend(mm.cc_responses(prefix, *args[1:]) or [])
                            return results
                        if not target.isdigit() and not target.startswith(
                            self._owned_prefix
                        ):
                            target = self._owned_prefix + target
                        args = (target, *args[1:])
                        kwargs.pop("id", None)
                    result = method(*args, **kwargs)
                    if name == "cc_commands":
                        for response in result:
                            headers = response.get("Header", [])
                            if "prefix" not in headers:
                                continue
                            index = headers.index("prefix")
                            rows = response.get("Tabular", [])
                            owned = [
                                row
                                for row in rows
                                if row[index].startswith(self._owned_prefix)
                            ]
                            for row in owned:
                                row[index] = row[index][len(self._owned_prefix) :]
                            response["Tabular"] = owned
                    return result
                finally:
                    # Leave no managed filter/prefix behind for ordinary users.
                    mm.clear_cc_filter()
                    mm.clear_cc_prefix()

        return call

    def _owned_prefixes(self, mm):
        prefixes = set()
        for response in mm.cc_commands():
            headers = response.get("Header") or []
            if "prefix" not in headers:
                continue
            index = headers.index("prefix")
            prefixes.update(
                row[index]
                for row in response.get("Tabular") or []
                if row[index].startswith(self._owned_prefix)
            )
        return sorted(prefixes)

    def _delete_owned(self, mm, target, commands):
        if target.isdigit():
            raise ValueError(
                "managed CC deletion requires an owned prefix; numeric IDs are host-local"
            )
        requested = (
            target
            if target.startswith(self._owned_prefix)
            else self._owned_prefix + target
        )
        prefixes = [
            prefix
            for prefix in self._owned_prefixes(mm)
            if target == "all" or prefix == requested
        ]
        previous = mm._raise_errors
        mm._raise_errors = False
        results = []
        try:
            for prefix in prefixes:
                # Minimega matches prefixes exactly. Response prefix lookup
                # depends on the command table, so remove responses first.
                methods = [mm.cc_delete_response]
                if commands:
                    methods.append(mm.cc_delete_command)
                for method in methods:
                    response = method(prefix) or []
                    for row in response:
                        error = row.get("Error", "")
                        if error and "no such prefix:" not in error:
                            raise RuntimeError(error)
                    results.extend(response)
            return results
        finally:
            mm._raise_errors = previous

    @property
    def _raise_errors(self):
        return self._connection._raise_errors

    @_raise_errors.setter
    def _raise_errors(self, value):
        self._connection._raise_errors = value
