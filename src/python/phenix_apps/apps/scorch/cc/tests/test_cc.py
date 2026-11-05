from unittest import mock

import pytest
from box import Box

from phenix_apps.apps.scorch.cc import cc
from phenix_apps.apps.scorch.cc.cc import CC, _one_line


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("whoami", "whoami"),
        ("rm -f /tmp/a\nrm -f /tmp/b\n", "rm -f /tmp/a\\nrm -f /tmp/b\\n"),
        ("dir C:\\temp\r\n", "dir C:\\temp\\r\\n"),
        (42, "42"),
    ],
)
def test_one_line_escapes_line_breaks(text, want):
    assert _one_line(text) == want


def test_stage_exec_logs_the_command_on_one_line(monkeypatch):
    component = object.__new__(CC)
    component.metadata = Box(
        {"start": [{"type": "exec", "args": "rm -f /tmp/a\nrm -f /tmp/b\n"}]}
    )
    component.mm = mock.Mock()
    component.extract_node_names = mock.Mock(return_value=[])
    info = mock.Mock()
    monkeypatch.setattr(cc.logger, "info", info)

    component.start()

    component.mm.cc_exec_once.assert_called_once_with("rm -f /tmp/a\nrm -f /tmp/b\n")
    info.assert_called_once_with(
        "command 'rm -f /tmp/a\\nrm -f /tmp/b\\n' executed with filter 'None' using cc"
    )
