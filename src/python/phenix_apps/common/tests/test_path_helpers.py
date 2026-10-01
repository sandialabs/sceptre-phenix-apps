"""
Characterization tests for the shared path-handling primitives.

These lock in the trust-boundary behavior the hardening work established:
``safe_join`` is the canonical way to join untrusted path components,
``validate_hostname`` gates hostnames at ingestion, and ``mm_recv`` refuses
non-normalized host destination paths before touching minimega.
"""

from unittest.mock import MagicMock

import pytest

from phenix_apps.common import utils
from phenix_apps.common.error import AppError


class TestValidateHostname:
    @pytest.mark.parametrize(
        "name",
        ["node-1", "A9", "web-server-01", "rtu1", "x" * 63],
    )
    def test_accepts(self, name):
        assert utils.validate_hostname(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "a",
            "42",
            "all",
            "Phenix",
            "web_server",
            "-leading",
            "trailing-",
            "_leading",
            "has space",
            "has/slash",
            "../traversal",
            "semi;colon",
            "new\nline",
            "x" * 64,
            "/etc/cron.d/x",
        ],
    )
    def test_rejects(self, name):
        with pytest.raises(AppError):
            utils.validate_hostname(name)


class TestSafeJoin:
    def test_plain_join_stays_inside(self, tmp_path):
        assert utils.safe_join(tmp_path, "a", "b") == tmp_path.resolve() / "a" / "b"

    def test_base_itself_is_allowed(self, tmp_path):
        assert utils.safe_join(tmp_path) == tmp_path.resolve()

    def test_internal_dotdot_that_stays_inside_is_allowed(self, tmp_path):
        assert utils.safe_join(tmp_path, "a/../b") == tmp_path.resolve() / "b"

    @pytest.mark.parametrize(
        "part",
        ["..", "../x", "a/../../x", "../../../../etc/cron.d/x"],
    )
    def test_traversal_out_of_base_rejected(self, tmp_path, part):
        with pytest.raises(AppError):
            utils.safe_join(tmp_path, part)

    def test_absolute_part_replacing_base_rejected(self, tmp_path):
        # pathlib semantics: an absolute component replaces the base entirely.
        # safe_join must catch exactly that footgun.
        with pytest.raises(AppError):
            utils.safe_join(tmp_path, "/etc/cron.d/x")


class TestMmRecvHostDstGuard:
    """mm_recv validates its host-side dst before any minimega interaction,
    so rejection cases need no minimega and acceptance cases stop at the
    first (mocked) minimega call instead of an AppError."""

    @pytest.mark.parametrize(
        "dst",
        [
            "relative/path",
            "/a/../b",
            "/a/..",
            "..",
            "/..",
            "/a/b/",
            "/a/b/.",
            "/a//b",
            "///a",
        ],
    )
    def test_rejects_non_normalized_dst(self, dst):
        with pytest.raises(AppError):
            utils.mm_recv(MagicMock(), "vm", "/src", dst)

    @pytest.mark.parametrize("dst", ["/a/b", "//a"])
    def test_normalized_absolute_dst_passes_guard(self, dst, monkeypatch):
        # "//a" documents the POSIX exactly-two-leading-slashes quirk the
        # guard inherited from os.path.normpath and deliberately preserves.
        def stop_after_guard(*args, **kwargs):
            raise RuntimeError("stop after guard")

        monkeypatch.setattr(utils, "mm_cc_client_active", stop_after_guard)
        with pytest.raises(RuntimeError, match="stop after guard"):
            utils.mm_recv(MagicMock(), "vm", "/src", dst)
