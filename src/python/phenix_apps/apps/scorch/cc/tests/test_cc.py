from pathlib import Path
from unittest.mock import MagicMock

import pytest

from phenix_apps.apps.scorch.app import parse_metadata, validate_metadata
from phenix_apps.apps.scorch.cc import cc as cc_mod
from phenix_apps.apps.scorch.cc.cc import CC, CCMetadata
from phenix_apps.common import error
from phenix_apps.testing.readme import readme_components

README = Path(__file__).parents[1] / "README.md"


def readme_examples() -> list[dict]:
    return readme_components(README, "cc")


def test_readme_has_examples():
    assert len(readme_examples()) >= 2


@pytest.mark.parametrize("cmp", readme_examples(), ids=lambda c: c["name"])
def test_readme_examples_are_valid_and_clean(cmp):
    _, warnings = validate_metadata(CCMetadata, cmp.get("metadata"), cmp["name"])
    assert warnings == []


def test_defaults_match_the_old_code():
    config = parse_metadata(
        CCMetadata,
        {
            "start": [{"type": "exec", "args": "whoami"}],
            "vms": [{"hostname": "aa", "start": [{"type": "exec", "args": "whoami"}]}],
        },
        "c",
    )

    # stage-level exec
    assert config.start[0].once is True
    assert config.start[0].filter is None
    # VM-level exec
    vm_exec = config.vms[0].start[0]
    assert vm_exec.once is True
    assert vm_exec.wait is False
    assert vm_exec.validator is None


def test_background_defaults():
    config = parse_metadata(
        CCMetadata,
        {"vms": [{"hostname": "aa", "start": [{"type": "background", "args": "x"}]}]},
        "c",
    )
    assert config.vms[0].start[0].once is True


@pytest.mark.parametrize(
    ("validator", "wait", "expected"),
    [
        ("exit 0", False, True),  # a validator forces wait, as the old code did
        (None, False, False),
        ("", False, False),  # "" was "no validator" to the old `if validator:`
        (None, True, True),
    ],
)
def test_validator_forces_wait(validator, wait, expected):
    cmd = {"type": "exec", "args": "x", "wait": wait}
    if validator is not None:
        cmd["validator"] = validator
    config = parse_metadata(
        CCMetadata, {"vms": [{"hostname": "aa", "start": [cmd]}]}, "c"
    )
    assert config.vms[0].start[0].wait is expected


@pytest.mark.parametrize(
    "shape",
    [
        # cc-empty-output: exec + wait + a validator that wants no output
        {
            "vms": [
                {
                    "hostname": "rtu-1",
                    "start": [
                        {
                            "type": "exec",
                            "args": "true",
                            "wait": True,
                            "validator": '[ -z "$(cat)" ] || { echo "$1: expected no output" >&2; exit 1; }',
                        }
                    ],
                }
            ]
        },
        # cc-output-parsing: exec with ':' and '/' in args and the validator
        {
            "vms": [
                {
                    "hostname": "rtu-1",
                    "start": [
                        {
                            "type": "exec",
                            "args": "echo 'warn: x' >&2; echo 'tcp 0 0 0.0.0.0:22 0.0.0.0:* LISTEN 812/sshd'",
                            "wait": True,
                            "validator": "out=$(cat); grep -Fxq 'x' <<<\"$out\"",
                        }
                    ],
                }
            ]
        },
    ],
)
def test_burger_cc_item_shapes_validate(shape):
    config, warnings = validate_metadata(CCMetadata, shape, "c")
    assert warnings == []
    assert config.vms[0].start[0].wait is True


@pytest.mark.parametrize(
    ("md", "message"),
    [
        ({"configure": [{"type": "bogus"}]}, "does not match any of the expected tags"),
        (
            {"vms": [{"hostname": "aa", "start": [{"type": "bogus", "args": "x"}]}]},
            "does not match any of the expected tags",
        ),
        ({"start": [{"type": "exec"}]}, "args"),
        ({"vms": [{"hostname": "aa", "start": [{"type": "exec"}]}]}, "args"),
        (
            {"vms": [{"hostname": "aa", "start": [{"type": "send", "args": "a:b:c"}]}]},
            "at most one",
        ),
        (
            {"vms": [{"hostname": "aa", "start": [{"type": "send", "args": ":"}]}]},
            "neither side empty",
        ),
        (
            {"vms": [{"hostname": "aa", "start": [{"type": "send", "args": "src:"}]}]},
            "neither side empty",
        ),
        (
            {"vms": [{"hostname": "aa", "start": [{"type": "recv", "args": ":dst"}]}]},
            "neither side empty",
        ),
        ({"vms": [{"hostname": "a"}]}, r"vms\.0\.hostname"),
        ({"vms": [{"hostname": "a;reboot"}]}, r"vms\.0\.hostname"),
        ({"start": [{"type": "exec", "args": "a\nb"}]}, "args"),
        ({"start": [{"type": "exec", "args": ""}]}, "args"),
    ],
)
def test_bad_metadata_is_rejected(md, message):
    with pytest.raises(ValueError, match=message):
        parse_metadata(CCMetadata, md, "c")


def test_unknown_vm_key_only_warns():
    md = {"vms": [{"hostname": "aa", "bogus": 1}]}
    _, warnings = validate_metadata(CCMetadata, md, "c")

    assert len(warnings) == 1
    assert warnings[0].startswith("vms.0.bogus: unknown key, ignored.")
    assert "(known:" in warnings[0]


def test_unknown_command_key_only_warns():
    md = {
        "vms": [
            {"hostname": "aa", "start": [{"type": "exec", "args": "x", "bogus": 1}]}
        ]
    }
    _, warnings = validate_metadata(CCMetadata, md, "c")

    assert warnings == [
        "vms.0.start.0.bogus: unknown key, ignored. Fix: remove it "
        "(known: type, args, once, wait, validator)"
    ]


def test_top_level_unknown_key_does_not_warn():
    # CCMetadata is a BaseModel, not a MetadataBlock, so a stray top-level key
    # is kept (extra="allow") without a warning.
    _, warnings = validate_metadata(CCMetadata, {"bogus": 1, "vms": []}, "c")
    assert warnings == []


def test_null_stage_list_is_empty():
    # an empty `start:` in YAML parses to None; take it as "nothing to do"
    config = parse_metadata(CCMetadata, {"start": None, "vms": None}, "c")
    assert config.start == []
    assert config.vms == []


def test_empty_stage_filter_means_no_filter():
    config = parse_metadata(
        CCMetadata, {"start": [{"type": "exec", "args": "x", "filter": ""}]}, "c"
    )
    assert config.start[0].filter is None


# Runtime: build a CC without __init__ and stub minimega and the utils.


def component(md, tmp_path, nodes=("aa",), os_type="linux"):
    comp = object.__new__(CC)
    comp.mm = MagicMock()
    comp.config = CCMetadata.model_validate(md)
    comp.base_dir = tmp_path
    comp.extract_node_names = lambda: list(nodes)
    comp.extract_node_os_type = lambda host: os_type
    comp._CC__send_cmd_as_file = lambda host, cmd: "bash /s.sh"
    return comp


def vm_md(cmd, stage="start"):
    return {"vms": [{"hostname": "aa", stage: [cmd]}]}


def stub_wait(monkeypatch, **results):
    out = {"stdout": "", "stderr": "", "exitcode": 0, **results}
    monkeypatch.setattr(cc_mod.utils, "mm_exec_wait", lambda *a, **k: out)


def test_exec_wait_nonzero_exit_raises(monkeypatch, tmp_path):
    stub_wait(monkeypatch, exitcode=1)
    comp = component(vm_md({"type": "exec", "args": "x", "wait": True}), tmp_path)
    with pytest.raises(RuntimeError, match="failed"):
        comp.start()


def test_exec_wait_windows_stderr_is_failure(monkeypatch, tmp_path):
    stub_wait(monkeypatch, stderr="boom")
    comp = component(
        vm_md({"type": "exec", "args": "x", "wait": True}), tmp_path, os_type="windows"
    )
    with pytest.raises(RuntimeError, match="Windows"):
        comp.start()


@pytest.mark.parametrize("enabled", [False, True])
def test_validator_skipped_when_host_validators_disabled(
    monkeypatch, tmp_path, enabled
):
    stub_wait(monkeypatch)
    monkeypatch.setattr(cc_mod, "SCORCH_HOST_VALIDATORS", enabled)
    run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(cc_mod.subprocess, "run", run)
    comp = component(
        vm_md({"type": "exec", "args": "x", "validator": "exit 0"}), tmp_path
    )

    comp.start()

    assert run.called is enabled


def test_validator_failure_raises(monkeypatch, tmp_path):
    stub_wait(monkeypatch)
    monkeypatch.setattr(cc_mod, "SCORCH_HOST_VALIDATORS", True)
    monkeypatch.setattr(
        cc_mod.subprocess,
        "run",
        lambda *a, **k: MagicMock(returncode=1, stderr=b"nope"),
    )
    comp = component(
        vm_md({"type": "exec", "args": "x", "validator": "exit 1"}), tmp_path
    )
    with pytest.raises(RuntimeError, match="validation failed"):
        comp.start()


def test_recv_absolute_dst_outside_base_dir_raises(tmp_path):
    comp = component(vm_md({"type": "recv", "args": "/etc/x:/etc/passwd"}), tmp_path)
    with pytest.raises(error.AppError, match="escapes"):
        comp.start()


def test_vm_not_in_topology_is_skipped(monkeypatch, tmp_path):
    send = MagicMock()
    monkeypatch.setattr(cc_mod.utils, "mm_send", send)
    comp = component(vm_md({"type": "send", "args": "f"}), tmp_path, nodes=("other",))

    comp.start()

    send.assert_not_called()


def test_stage_reset_calls_reset_cc(monkeypatch, tmp_path):
    reset = MagicMock()
    monkeypatch.setattr(CC, "_CC__reset_cc", reset)
    comp = component({"start": [{"type": "reset"}]}, tmp_path)

    comp.start()

    reset.assert_called_once()
