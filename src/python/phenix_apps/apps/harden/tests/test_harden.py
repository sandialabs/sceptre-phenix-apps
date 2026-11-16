import io
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from phenix_apps.apps.harden.app import Harden, HostPlan
from phenix_apps.apps.harden.models import (
    HardenMetadata,
    SshSpec,
    derive_password,
    meets_windows_policy,
)
from phenix_apps.common.error import AppError
from phenix_apps.common.metadata import validate_metadata

APP_DIR = Path(__file__).parents[1]

SEED = "minihard-macroharder"
LITERAL = "Tr0ub4dor&3!!"
LOCKED = SshSpec(root_login="no", empty_passwords="no")
ADMIN = {"Administrator": LITERAL}


def node(hostname, os_type="linux", **extra):
    hardware = {"os_type": os_type, **extra.pop("hardware", {})}
    return {"general": {"hostname": hostname}, "hardware": hardware, **extra}


def bare(**general):
    return {"general": {"hostname": "vm", **general}}


def linux(**block):
    return {"linux": block}


def windows(**block):
    return {"windows": block}


def user(name, **spec):
    return {"users": {name: spec or {"generate": True}}}


def derived(host, username):
    return derive_password(SEED, host, username)


NODES = [node("web"), node("db", "centos"), node("win", "windows")]
METADATA = {
    "seed": SEED,
    **linux(**user("root"), ssh={"root_login": "no", "empty_passwords": "no"}),
    **windows(**user("Administrator", password=LITERAL), remove_users=["vagrant"]),
}


def make_app(monkeypatch, tmp_path, metadata=METADATA, hosts=None, nodes=NODES):
    """A real Harden, built from an experiment on stdin as phenix core sends it."""

    app = {"name": "harden", "metadata": metadata, "hosts": hosts}
    spec = {
        "experimentName": "macroharder",
        "baseDir": str(tmp_path),
        "topology": {"nodes": nodes},
        "scenario": {"apps": [app]},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"spec": spec})))
    return Harden("harden", "pre-start")


def plans_of(app):
    return {plan.hostname: plan for plan in app.plan()}


# -- passwords and metadata ----------------------------------------------------


def test_derived_password_is_the_documented_value():
    # the README shows this derivation; keep both in step
    seed = "correct-horse-battery-staple"
    assert derive_password(seed, "webserv01", "root") == "Kq2!r7UlN6nNL5KL"


def test_derived_passwords_are_distinct_and_pass_the_windows_policy():
    seeds, hosts = ("minihard", "macroharder"), ("colossus", "colossus-2")
    users = ("root", "Administrator", "grok")
    inputs = [(s, h, u) for s in seeds for h in hosts for u in users]
    passwords = [derive_password(*each) for each in inputs]

    assert len(set(passwords)) == len(inputs)
    for (_, _, username), password in zip(inputs, passwords, strict=True):
        assert re.fullmatch(r"[A-Z][a-z][0-9][!-][A-Za-z0-9!-]{12}", password)
        assert meets_windows_policy(password, username)


@pytest.mark.parametrize(
    ("password", "username", "ok"),
    [
        ("Passw0rd", "bob", True),
        ("pass word 1", "bob", False),  # a space is not a symbol
        ("password1", "bob", False),
        ("12345678!", "bob", False),
        ("Bobby-Tables1", "bob", False),  # the account name, in any case
        ("ab-Pass1", "ab", True),  # names under three characters are not checked
    ],
)
def test_windows_policy(password, username, ok):
    assert meets_windows_policy(password, username) is ok


@pytest.mark.parametrize(
    ("md", "problem"),
    [
        (linux(users={"bob": {}}), "exactly one of 'password'"),
        (linux(**user("bob", generate=False)), "exactly one of 'password'"),
        (linux(**user("bob", password=LITERAL, generate=True)), "exactly one of"),
        (linux(**user("bob", generate="true")), "users.bob.generate"),
        (linux(**user("bob", password="short77")), "at least 8"),
        (linux(**user("bob", password="x" * 128)), "at most 127"),
        (linux(**user("bob", password="has\nnewline")), "pattern"),
        (linux(**user("bob", password="pässwörd")), "pattern"),
        (linux(**user("bad name")), "pattern"),
        (linux(**user("bob;reboot")), "pattern"),
        (linux(**user("b" * 33)), "pattern"),
        (windows(**user("b" * 21)), "pattern"),
        (windows(**user("bob ")), "pattern"),
        (linux(remove_users=["$(reboot)"]), "remove_users.0"),
        (linux(remove_users=["root"]), "built in"),
        (windows(remove_users=["ADMINISTRATOR"]), "built in"),
        (linux(**user("bob"), remove_users=["bob"]), "also in users"),
        (linux(ssh={"root_login": "yes"}), "linux.ssh.root_login"),
        # an unquoted YAML `no` arrives as False
        (linux(ssh={"empty_passwords": False}), "linux.ssh.empty_passwords"),
        (windows(autologon="off"), "windows.autologon"),
        (windows(**user("bob", password="alllowercase")), "needs three of"),
        (windows(**user("bob", password="Bobby-Tables1")), "the account name"),
        ({"seed": "minhard"}, "seed"),  # one short; minihard just fits
        ({"exclude": ["-bad"]}, "exclude.0"),
    ],
)
def test_metadata_rejects(md, problem):
    with pytest.raises(ValueError, match="invalid metadata for app 'harden'") as ex:
        validate_metadata(HardenMetadata, md, "harden", "app")

    assert problem in str(ex.value)


# -- planning ------------------------------------------------------------------


def test_plan_targets_every_hardenable_vm(monkeypatch, tmp_path):
    metadata = {**METADATA, "exclude": ["db"]}
    nodes = [*NODES, node("router", "vyos", type="Router")]

    web = {"users": {"root": derived("web", "root")}, "ssh": LOCKED}
    win = {"users": ADMIN, "remove_users": ["vagrant"]}

    assert plans_of(make_app(monkeypatch, tmp_path, metadata, nodes=nodes)) == {
        "web": HostPlan(hostname="web", os_type="linux", **web),
        "win": HostPlan(hostname="win", os_type="windows", **win),
    }


@pytest.mark.parametrize(
    ("target", "hardened"),
    [
        (node("vm", "rhel"), True),
        (node("vm", "centos"), True),
        (node("vm", "Windows"), True),
        (bare(), True),  # an unset os_type is linux
        (node("vm", "minirouter"), False),
        (node("vm", "unknown"), False),
        (node("vm", "linux", type="Router"), False),
        (bare() | {"external": True}, False),
        (node("vm", "linux", external=True), False),
        (bare(do_not_boot=True), False),
    ],
)
def test_plan_node_kinds(monkeypatch, tmp_path, target, hardened):
    app = make_app(monkeypatch, tmp_path, nodes=[target])

    assert list(plans_of(app)) == (["vm"] if hardened else [])

    # a hosts entry for a VM that cannot be hardened is an error, not a skip
    app = make_app(monkeypatch, tmp_path, hosts=[{"hostname": "vm"}], nodes=[target])
    if hardened:
        assert list(plans_of(app)) == ["vm"]
    else:
        with pytest.raises(AppError, match="host 'vm' cannot be hardened"):
            app.plan()


@pytest.mark.parametrize(
    ("host", "override", "changed"),
    [
        ("web", None, {}),
        ("web", {}, {}),
        # users merge by name, and a host's entry replaces the block's
        ("win", user("bob"), {"users": ADMIN | {"bob": derived("win", "bob")}}),
        ("web", user("root", password=LITERAL), {"users": {"root": LITERAL}}),
        # a list is replaced, and an empty one clears the block's
        ("win", {"remove_users": ["guest"]}, {"remove_users": ["guest"]}),
        ("win", {"remove_users": []}, {"remove_users": []}),
        ("win", {"autologon": "disable"}, {"autologon": "disable"}),
        # a nested block merges field by field
        ("web", {"ssh": {"root_login": "prohibit-password"}}, {"ssh": "merged"}),
    ],
)
def test_plan_merges_host_metadata_over_the_os_block(
    monkeypatch, tmp_path, host, override, changed
):
    entry = {"hostname": host} | ({} if override is None else {"metadata": override})
    if "ssh" in changed:
        changed = {"ssh": LOCKED.model_copy(update=override["ssh"])}
    expected = plans_of(make_app(monkeypatch, tmp_path))
    expected[host] = expected[host].model_copy(update=changed)

    assert plans_of(make_app(monkeypatch, tmp_path, hosts=[entry])) == expected


@pytest.mark.parametrize(
    ("host", "override", "problem"),
    [
        ("win", {"remove_users": ["Administrator"]}, "built in"),
        ("win", user("bob", password="alllowercase"), "needs three of"),
        ("web", {"ssh": {"root_login": "yes"}}, "ssh.root_login"),
        # valid alone, but the block removes the account it sets a password for
        ("win", user("vagrant"), "'vagrant' is also in users"),
    ],
)
def test_plan_rejects_host_metadata(monkeypatch, tmp_path, host, override, problem):
    hosts = [{"hostname": host, "metadata": override}]
    app = make_app(monkeypatch, tmp_path, hosts=hosts)

    with pytest.raises(ValueError, match=f"metadata for harden host '{host}'") as ex:
        app.plan()

    assert problem in str(ex.value)
    assert LITERAL not in str(ex.value)


@pytest.mark.parametrize(
    ("metadata", "hosts", "message"),
    [
        (linux(**user("root")), None, "'seed' is required .* of 'root' on 'web'"),
        (METADATA, [{"hostname": "nope"}], "host 'nope' is not in the topology"),
        (METADATA | {"exclude": ["nope"]}, None, "excluded host 'nope' is not in"),
        (METADATA | {"exclude": ["web"]}, [{"hostname": "web"}], "is also excluded"),
    ],
)
def test_plan_rejects(monkeypatch, tmp_path, metadata, hosts, message):
    app = make_app(monkeypatch, tmp_path, metadata, hosts=hosts)

    with pytest.raises(AppError, match=message):
        app.plan()


def test_plan_needs_no_seed_for_literal_passwords(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, linux(**user("root", password=LITERAL)))

    assert plans_of(app)["web"].users == {"root": LITERAL}


def annotated(key, value):
    return {"annotations": {f"phenix/{key}": value}}


def drives(*each):
    return {"hardware": {"drives": list(each)}}


@pytest.mark.parametrize(
    ("os_type", "extra", "explicit", "why"),
    [
        ("linux", annotated("startup-via-cc", True), False, "startup-via-cc"),
        ("linux", annotated("startup-via-cc", "false"), False, None),
        ("linux", {"labels": {"disable-injects": ""}}, False, "disable-injects"),
        ("linux", drives({"inject_partition": 0}), False, "inject_partition 0"),
        ("linux", drives({"inject_partition": 1}), False, None),
        (
            "linux",
            {"general": {"hostname": "odd", "snapshot": False}},
            False,
            "snapshot",
        ),
        ("linux", drives(), False, None),
        ("linux", {"annotations": None, "labels": None}, False, None),
        ("linux", annotated("default-apps", False), False, None),
        ("windows", annotated("default-apps", False), False, "startup script"),
        ("windows", annotated("domain-controller", False), False, None),
        ("windows", annotated("domain-controller", "true"), False, "domain contr"),
        # a hosts entry lets a domain controller through, and nothing else
        ("windows", annotated("domain-controller", "true"), True, None),
        ("windows", annotated("startup-via-cc", "1"), True, "startup-via-cc"),
    ],
)
def test_plan_refusals(monkeypatch, tmp_path, os_type, extra, explicit, why):
    hosts = [{"hostname": "odd"}] if explicit else None
    nodes = [node("web"), node("odd", os_type, **extra)]
    app = make_app(monkeypatch, tmp_path, hosts=hosts, nodes=nodes)

    if why is None:
        assert list(plans_of(app)) == ["web", "odd"]
        return

    with pytest.raises(AppError, match=r"harden refuses 1 VM\(s\): odd: ") as ex:
        app.plan()
    assert why in str(ex.value)


def test_plan_lists_every_refusal_but_an_excluded_vm(monkeypatch, tmp_path):
    dc = annotated("domain-controller", "true")
    cc = node("cc", **annotated("startup-via-cc", True))
    nodes = [node("dc1", "windows", **dc), node("dc2", "windows", **dc), cc]
    app = make_app(monkeypatch, tmp_path, METADATA | {"exclude": ["dc2"]}, nodes=nodes)

    with pytest.raises(AppError, match=r"refuses 2 VM\(s\): dc1: .*; cc: "):
        app.plan()


# -- Linux script --------------------------------------------------------------

# Logs its call, and fails when STUB_FAIL names it or `name:last-argument`.
STUB = """#!/bin/bash
name=${0##*/}
echo "$name $*" >> "$STUB_LOG"
if [ "$name" = chpasswd ]; then cat >> "$STUB_LOG"; fi
for failing in $STUB_FAIL; do
    if [ "$failing" = "$name" ] || [ "$failing" = "$name:${!#}" ]; then exit 1; fi
done
exit 0
"""

SSHD_CONFIG = """\
Include /etc/ssh/sshd_config.d/*.conf
#PermitRootLogin prohibit-password
  permitrootlogin yes
PermitRootLoginExtra yes
#PermitEmptyPasswords no
"""
SSHD_DIRECTIVES = "PermitEmptyPasswords no\nPermitRootLogin no\n"
PAM = {
    "pam.d/common-auth": "auth [success=1 default=ignore] pam_unix.so nullok\n",
    "pam.d/system-auth": "auth sufficient pam_unix.so nullok_secure try_first_pass\n",
    "pam.d/other": "auth required pam_unix.so nullok\n",
}


def run_linux(app, tmp_path, files, fail="", **plan):
    """Run a host's rendered script with /etc and /run moved under tmp_path and
    the system commands stubbed. Returns the command log and the moved /etc."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("chpasswd", "id", "pkill", "userdel", "sshd", "systemctl"):
        (bin_dir / name).write_text(STUB)
        (bin_dir / name).chmod(0o755)

    etc = tmp_path / "root" / "etc"
    for path, text in {"phenix/startup/.keep": "", **files}.items():
        (etc / path).parent.mkdir(parents=True, exist_ok=True)
        (etc / path).write_text(text)

    app.harden_dir.mkdir()
    script = app.render_script(HostPlan(hostname="web", os_type="linux", **plan))
    script.write_text(re.sub("/(etc|run)/", rf"{etc.parent}/\1/", script.read_text()))
    log = tmp_path / "commands.log"
    log.touch()
    path = f"{bin_dir}:{os.environ['PATH']}"
    env = {"PATH": path, "STUB_LOG": str(log), "STUB_FAIL": fail}
    subprocess.run(["bash", str(script)], env=env, check=False, capture_output=True)

    assert not script.exists()  # it deletes itself, pass or fail
    return log.read_text(), etc


@pytest.mark.parametrize(
    "password",
    [
        "p'a$s\"w`ord",
        "back\\slash #hash\\",
        " spaced ",
        "${7*7} <% x %> %y",
        "PHENIX_HARDEN",
    ],
)
def test_linux_script_passes_a_password_verbatim(monkeypatch, tmp_path, password):
    files = {"ssh/sshd_config": SSHD_CONFIG, **PAM}
    users = {"root": password, "ops": LITERAL}

    log, etc = run_linux(make_app(monkeypatch, tmp_path), tmp_path, files, users=users)

    assert log == f"chpasswd \nroot:{password}\nchpasswd \nops:{LITERAL}\n"
    assert (etc / "phenix/harden.result").read_text() == "ok\n"
    # with no ssh option set, sshd and PAM are left alone
    assert {name: (etc / name).read_text() for name in files} == files


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        # the directives go first, and their other lines are dropped
        (
            SSHD_CONFIG,
            SSHD_DIRECTIVES
            + "Include /etc/ssh/sshd_config.d/*.conf\nPermitRootLoginExtra yes\n",
        ),
        ("Port 22\n", SSHD_DIRECTIVES + "Port 22\n"),
    ],
)
def test_linux_script_locks_sshd_and_pam(monkeypatch, tmp_path, config, expected):
    files = {"ssh/sshd_config": config, **PAM}

    log, etc = run_linux(make_app(monkeypatch, tmp_path), tmp_path, files, ssh=LOCKED)

    assert log == "sshd -t\nsystemctl try-reload-or-restart ssh\n"
    assert (etc / "phenix/harden.result").read_text() == "ok\n"
    assert {name: (etc / name).read_text() for name in files} == {
        "ssh/sshd_config": expected,
        "pam.d/common-auth": "auth [success=1 default=ignore] pam_unix.so\n",
        "pam.d/system-auth": "auth sufficient pam_unix.so try_first_pass\n",
        "pam.d/other": PAM["pam.d/other"],
    }
    assert (etc.parent / "run/sshd").is_dir()


@pytest.mark.parametrize(
    ("fail", "result", "last_command"),
    [
        ("chpasswd", "harden: set the password of root", "chpasswd "),
        ("userdel", "harden: remove rdp", "userdel -r -f rdp"),
        ("sshd", "harden: sshd rejected the edited configuration", "sshd -t"),
        ("systemctl", "harden: reload sshd", "systemctl try-reload-or-restart sshd"),
        # the unit is `sshd` where it is not `ssh`
        ("systemctl:ssh", "ok", "systemctl try-reload-or-restart sshd"),
        ("pkill", "ok", "systemctl try-reload-or-restart ssh"),
        # an account that is already gone is not an error
        ("id:rdp", "ok", "systemctl try-reload-or-restart ssh"),
    ],
)
def test_linux_script_reports_the_step_that_failed(
    monkeypatch, tmp_path, fail, result, last_command
):
    plan = {"users": {"root": LITERAL}, "remove_users": ["rdp"], "ssh": LOCKED}
    files = {"ssh/sshd_config": "Port 22\n"}

    log, etc = run_linux(make_app(monkeypatch, tmp_path), tmp_path, files, fail, **plan)

    commands = [line for line in log.splitlines() if line != f"root:{LITERAL}"]
    assert (etc / "phenix/harden.result").read_text() == f"{result}\n"
    assert commands[-1] == last_command
    assert ("userdel -r -f rdp" in commands) is (fail not in ("chpasswd", "id:rdp"))


# -- Windows script ------------------------------------------------------------


def render_windows(app, **plan):
    app.harden_dir.mkdir(exist_ok=True)
    plan = HostPlan(hostname="win", os_type="windows", **plan)
    return app.render_script(plan).read_text()


@pytest.mark.parametrize(
    ("password", "literal"),
    [
        ("it's $100", "'it''s $100'"),
        ("'quoted'", "'''quoted'''"),
        ('"dq" `n $(calc) $env:X', "'\"dq\" `n $(calc) $env:X'"),
        ("${7*7} <% x %>", "'${7*7} <% x %>'"),
    ],
)
def test_windows_script_quotes_a_password(monkeypatch, tmp_path, password, literal):
    script = render_windows(make_app(monkeypatch, tmp_path), users={"bob": password})

    assert f"    $password = {literal}\n" in script


def test_windows_script_steps_and_autologon(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path)
    plan = {"users": ADMIN, "remove_users": ["vagrant"]}
    keep = render_windows(app, **plan)
    disable = render_windows(app, autologon="disable", **plan)

    # waits for phenix's last reboot, refuses before changing anything, and
    # deletes itself whatever happens
    steps = [
        "if (-not $phenix -or $phenix.GetValue('startup') -ne 'done') { exit }",
        'throw "cannot remove the autologon user vagrant while autologon is kept"',
        'throw "no local user Administrator"',
        "$users['Administrator'].SetPassword($password)",
        "Set-ItemProperty -Path $winlogon -Name DefaultPassword -Value $password",
        "StartName='.\\\\Administrator' OR StartName='$env:COMPUTERNAME\\\\Admin",
        "Win32_UserProfile",
        "$computer.Delete('user', 'vagrant')",
        "Set-Content -Path $result -Value 'ok'",
        "} finally {\n    Remove-Item -LiteralPath $PSCommandPath",
    ]
    positions = [keep.find(step) for step in steps]
    assert -1 not in positions, steps[positions.index(-1)]
    assert positions == sorted(positions)
    assert "-Name AutoAdminLogon" not in keep

    assert "Set-ItemProperty -Path $winlogon -Name AutoAdminLogon -Value '0'" in disable
    assert "Remove-ItemProperty -Path $winlogon -Name DefaultPassword" in disable
    assert "-Name DefaultPassword -Value" not in disable
    assert "cannot remove the autologon user" not in disable
    for script in (keep, disable):
        assert script.count("{") == script.count("}")


# -- pre-start -----------------------------------------------------------------


def test_pre_start_on_the_dry_run_input(monkeypatch, tmp_path):
    experiment = yaml.safe_load((APP_DIR / "tests" / "harden_input.yaml").read_text())
    experiment["spec"]["baseDir"] = str(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(experiment)))
    app = Harden("harden", "pre-start")
    out = tmp_path / "harden"

    app.execute_stage()
    app.execute_stage()  # an experiment restart must not inject twice

    nodes = json.loads(app.experiment.to_json())["spec"]["topology"]["nodes"]
    injects = {n["general"]["hostname"]: n.get("injections", []) for n in nodes}
    placed = {h: [(i["src"], i["dst"]) for i in each] for h, each in injects.items()}
    assert placed == {
        "web": [(str(out / "web.sh"), "/etc/phenix/startup/50-harden.sh")],
        "win": [(str(out / "win.ps1"), "/phenix/startup/50-harden.ps1")],
        "router": [],
        "kali": [],
    }
    assert {i["permissions"] for each in injects.values() for i in each} == {"0600"}
    modes = {path.name: stat.S_IMODE(path.stat().st_mode) for path in out.iterdir()}
    assert modes == {"web.sh": 0o600, "win.ps1": 0o600, "credentials.yml": 0o600}

    admin = {"Administrator": derived("win", "Administrator"), "engineer": LITERAL}
    web = {"os": "linux", "users": {"root": derived("web", "root")}, "removed": []}
    win = {"os": "windows", "users": admin, "removed": ["vagrant"]}
    recorded = yaml.safe_load((out / "credentials.yml").read_text())
    assert recorded == {"hosts": {"web": web, "win": win}}


def test_pre_start_with_nothing_to_harden_writes_nothing(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, nodes=[node("router", "vyos", type="Router")])

    app.pre_start()

    assert "injections" not in app.experiment.spec.topology.nodes[0]
    assert not (tmp_path / "harden").exists()
