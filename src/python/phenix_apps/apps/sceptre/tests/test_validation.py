"""Tests for the scenario pre-flight check.

The parametrized table below is the important one: each row is a mistake a user
actually makes, and it asserts both that the check fires and that it names the
host and field. The rows were derived by breaking the golden fixture and
recording what the app did before validation existed -- every "fatal" row was a
crash (KeyError, IndexError, BoxKeyError, UnboundLocalError) and every non-fatal
row was a silent no-op.
"""

import pytest

from phenix_apps.apps.sceptre import validation
from phenix_apps.apps.sceptre.configs import configs
from phenix_apps.apps.sceptre.configs.infrastructures import INFRASTRUCTURES
from phenix_apps.apps.sceptre.metadata import (
    Infrastructure,
    SceptreMetadataParser,
    Simulator,
)
from phenix_apps.apps.sceptre.tests.conftest import (
    drop_topo_node,
    host,
    only_mgmt_interface,
    topo_node,
)
from phenix_apps.common import error


def problems_for(app):
    return validation.validate(app)


def messages(problems):
    return " | ".join(f"{p.hostname}:{p.message}" for p in problems)


def test_register_overrides_are_accepted(scenario):
    """They are what the infrastructure table honours, not a mistake."""

    app = scenario(
        lambda e: (
            host(e, "rtu-1").metadata.dnp3[0].__setitem__("analog-read", ["voltage"])
        )
    )

    assert validation.validate(app) == []


def test_a_fep_need_not_declare_a_protocol(scenario):
    """Unlike an fd-server: its devices can come from the RTUs it adopts."""

    app = scenario(lambda e: host(e, "fep-1").metadata.pop("dnp3"))

    assert validation.validate(app) == []


def test_clean_scenario_has_no_problems(scenario):
    """The guard against false positives.

    Every fatal check must correspond to something that already crashed, so a
    scenario that works today must come through completely clean -- otherwise
    this module would reject configurations that previously built fine.
    """

    assert validation.validate(scenario()) == []


# (id, mutation, fatal?, fragment that must appear in the message)
CASES = [
    (
        "fd-server provider typo",
        lambda e: host(e, "rtu-1").metadata.__setitem__("provider", "provider-pww"),
        True,
        "metadata.provider 'provider-pww' matches no provider host",
    ),
    (
        "fd-server missing provider",
        lambda e: host(e, "rtu-1").metadata.pop("provider"),
        True,
        "metadata.provider is required",
    ),
    (
        "fd-server missing infrastructure",
        lambda e: host(e, "rtu-1").metadata.pop("infrastructure"),
        True,
        "metadata.infrastructure is required",
    ),
    (
        "fd-server unknown infrastructure",
        lambda e: host(e, "rtu-1").metadata.__setitem__(
            "infrastructure", "power-transmision"
        ),
        True,
        "is not supported",
    ),
    (
        "fd-server device missing name",
        lambda e: host(e, "rtu-1").metadata.dnp3[0].pop("name"),
        True,
        "metadata.dnp3[0] is missing 'name'",
    ),
    (
        "fd-server device type typo",
        lambda e: host(e, "rtu-1").metadata.dnp3[0].__setitem__("type", "generatorr"),
        True,
        "type 'generatorr' is not valid for power-transmission",
    ),
    (
        "fd-server device with an unknown key",
        lambda e: host(e, "rtu-1").metadata.dnp3[0].__setitem__("analog-reed", ["v"]),
        True,
        "unsupported key(s): analog-reed",
    ),
    (
        "fd-server server_hostname typo",
        lambda e: host(e, "rtu-1").metadata.__setitem__("server_hostname", "nope"),
        True,
        "metadata.server_hostname 'nope' matches no host",
    ),
    (
        "host missing from topology",
        lambda e: drop_topo_node(e, "rtu-2"),
        True,
        "missing from the topology",
    ),
    (
        "topology node with no interfaces",
        lambda e: topo_node(e, "provider-pp").network.__setitem__("interfaces", []),
        True,
        "no network interfaces",
    ),
    (
        "PowerWorld provider missing case",
        lambda e: host(e, "provider-pw").metadata.pop("case"),
        True,
        "metadata.case is required when simulator is 'PowerWorld'",
    ),
    (
        "PyPower provider missing case",
        lambda e: host(e, "provider-pp").metadata.pop("case"),
        True,
        "metadata.case is required when simulator is 'PyPower'",
    ),
    (
        "opc with only a mgmt interface",
        lambda e: only_mgmt_interface(e, "opc-1"),
        True,
        'OPC needs an interface on a vlan other than "mgmt"',
    ),
    (
        "historian with only a mgmt interface",
        lambda e: only_mgmt_interface(e, "hist-1"),
        True,
        'historian needs an interface on a vlan other than "mgmt"',
    ),
    (
        "fd-client with only a mgmt interface",
        lambda e: only_mgmt_interface(e, "client-1"),
        True,
        "fd-client needs a non-mgmt, non-serial interface",
    ),
    (
        "helics federate broker typo",
        lambda e: host(e, "fed-helics").metadata.helics.__setitem__("broker", "nope"),
        True,
        "metadata.helics.broker 'nope' matches no host",
    ),
    (
        "fep missing provider",
        lambda e: host(e, "fep-1").metadata.pop("provider"),
        True,
        "metadata.provider is required on fep hosts",
    ),
    (
        "fep connected_rtus typo",
        lambda e: host(e, "fep-1").metadata.__setitem__("connected_rtus", ["rtu-nope"]),
        False,
        "metadata.connected_rtus references 'rtu-nope'",
    ),
    (
        "opc connected_rtus typo",
        lambda e: host(e, "opc-1").metadata.__setitem__("connected_rtus", ["rtu-nope"]),
        False,
        "metadata.connected_rtus references 'rtu-nope'",
    ),
    (
        "fd-client connected_rtus typo",
        lambda e: host(e, "client-1").metadata.__setitem__(
            "connected_rtus", ["rtu-nope"]
        ),
        False,
        "metadata.connected_rtus references 'rtu-nope'",
    ),
    (
        "engineer-workstation connected_rtus typo",
        lambda e: host(e, "eng-1").metadata.__setitem__("connected_rtus", ["rtu-nope"]),
        False,
        "metadata.connected_rtus references 'rtu-nope'",
    ),
    (
        "hmi connected_scadas typo",
        lambda e: host(e, "hmi-1").metadata.__setitem__(
            "connected_scadas", ["scada-nope"]
        ),
        False,
        "metadata.connected_scadas references 'scada-nope'",
    ),
    (
        "historian primary typo",
        lambda e: host(e, "hist-2-bak").metadata.__setitem__("primary", "hist-nope"),
        False,
        "metadata.primary 'hist-nope' matches no host",
    ),
    (
        "fd-server declares no protocol",
        lambda e: host(e, "rtu-1").metadata.pop("dnp3"),
        False,
        "declares no protocol",
    ),
    (
        "provider without a simulator",
        lambda e: host(e, "provider-pp").metadata.pop("simulator"),
        False,
        "metadata.simulator is not set",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "fatal", "fragment"),
    [pytest.param(m, f, t, id=i) for i, m, f, t in CASES],
)
def test_detects(scenario, mutate, fatal, fragment):
    found = problems_for(scenario(mutate))

    matching = [p for p in found if fragment in p.message]
    assert matching, f"no problem matched {fragment!r}; got: {messages(found)}"
    assert matching[0].fatal is fatal


def test_reports_every_problem_at_once(scenario):
    """The whole point: one run surfaces the backlog, not one item per run."""

    app = scenario(
        lambda e: (
            host(e, "rtu-1").metadata.__setitem__("provider", "nope"),
            host(e, "rtu-2").metadata.pop("infrastructure"),
            host(e, "provider-pw").metadata.pop("case"),
            host(e, "opc-1").metadata.__setitem__("connected_rtus", ["rtu-nope"]),
        )
    )

    found = problems_for(app)
    hosts = {p.hostname for p in found}

    assert {"rtu-1", "rtu-2", "provider-pw", "opc-1"} <= hosts
    assert sum(p.fatal for p in found) == 3
    assert sum(not p.fatal for p in found) == 1


def test_missing_topology_node_suppresses_downstream_noise(scenario):
    """A host with no topology node yields one problem, not a cascade.

    Every later check dereferences topology, so reporting them all would bury
    the single edit that actually fixes it.
    """

    found = problems_for(scenario(lambda e: drop_topo_node(e, "rtu-1")))

    assert [p.hostname for p in found] == ["rtu-1"]
    assert "missing from the topology" in found[0].message


class TestSuggestions:
    def test_offers_a_near_miss(self, scenario):
        app = scenario(
            lambda e: host(e, "rtu-1").metadata.__setitem__("provider", "provider-pww")
        )

        problem = next(p for p in problems_for(app) if p.hostname == "rtu-1")
        assert problem.hint == "did you mean 'provider-pw'?"

    def test_lists_candidates_when_nothing_is_close(self, scenario):
        app = scenario(
            lambda e: host(e, "rtu-1").metadata.__setitem__("provider", "zzzzzz")
        )

        problem = next(p for p in problems_for(app) if p.hostname == "rtu-1")
        providers = sorted(p.hostname for p in app.extract_nodes_type("provider"))
        assert problem.hint == "known: " + ", ".join(providers)


class TestReport:
    def test_groups_by_severity_and_names_each_host(self):
        text = validation.report(
            [
                validation.Problem("rtu-1", "boom", "try this"),
                validation.Problem("opc-1", "hmm", fatal=False),
            ]
        )

        assert "2 errors" not in text
        assert "1 error and 1 warning" in text
        assert text.index("ERRORS") < text.index("WARNINGS")
        assert "rtu-1  boom" in text
        assert "-> try this" in text

    def test_scenario_wide_problems_are_labelled(self):
        text = validation.report([validation.Problem(None, "no provider is defined")])

        assert "scenario  no provider is defined" in text


class TestEnforce:
    def test_raises_on_a_fatal_problem(self, scenario, caplog):
        """AppError, so AppBase.execute_stage logs it and exits.

        The report is logged first, as its own record: the exception message
        only says how many errors there were, since a traceback is no place to
        read a report from.
        """

        app = scenario(lambda e: host(e, "rtu-1").metadata.pop("provider"))

        with pytest.raises(error.AppError, match="1 error"):
            validation.enforce(app)

        assert "metadata.provider is required on fd-server hosts" in caplog.text

    def test_warnings_alone_do_not_stop_the_run(self, scenario, caplog):
        app = scenario(
            lambda e: host(e, "opc-1").metadata.__setitem__(
                "connected_rtus", ["rtu-nope"]
            )
        )

        validation.enforce(app)  # must not raise

        assert "connected_rtus references 'rtu-nope'" in caplog.text

    def test_clean_scenario_logs_nothing(self, scenario, caplog):
        validation.enforce(scenario())

        assert caplog.text == ""


class TestMalformedTypes:
    """A validator that crashes is worse than no validator.

    These are scalar-where-a-list-belongs slips, which YAML makes easy. Before
    the type guards two of them raised out of validate() itself and the third
    reported one bogus problem per character of the string.
    """

    @pytest.mark.parametrize(
        ("mutate", "fragment"),
        [
            pytest.param(
                lambda e: host(e, "opc-1").metadata.__setitem__(
                    "connected_rtus", "rtu-1"
                ),
                "metadata.connected_rtus must be a list, got str",
                id="reference-list-as-string",
            ),
            pytest.param(
                lambda e: host(e, "rtu-1").metadata.__setitem__(
                    "dnp3", {"type": "bus", "name": "b"}
                ),
                "metadata.dnp3 must be a list",
                id="protocol-as-mapping",
            ),
            pytest.param(
                lambda e: host(e, "rtu-1").metadata.__setitem__("dnp3", ["bus-1"]),
                "metadata.dnp3[0] must be a mapping",
                id="protocol-list-of-strings",
            ),
            pytest.param(
                lambda e: host(e, "rtu-1").metadata.__setitem__(
                    "infrastructure", ["power-transmission"]
                ),
                "metadata.infrastructure must be a string",
                id="infrastructure-as-list",
            ),
        ],
    )
    def test_reports_instead_of_raising(self, scenario, mutate, fragment):
        found = problems_for(scenario(mutate))

        assert any(fragment in p.message for p in found), messages(found)

    def test_string_reference_yields_one_problem_not_one_per_character(self, scenario):
        app = scenario(
            lambda e: host(e, "opc-1").metadata.__setitem__("connected_rtus", "rtu-1")
        )

        assert len([p for p in problems_for(app) if p.hostname == "opc-1"]) == 1


def test_infrastructures_match_configs():
    """Guard against drift between the enum and the infrastructure table."""

    assert set(Infrastructure) == set(INFRASTRUCTURES)

    for name in Infrastructure:
        assert configs.get_fdconfig_class(name) is not None

    with pytest.raises(error.AppError, match="not supported"):
        configs.get_fdconfig_class("definitely-not-an-infrastructure")


def test_protocol_fields_match_the_parser():
    """The model declares one field per protocol the parser reads."""

    assert set(validation.PROTOCOL_FIELDS) == set(SceptreMetadataParser.protocols)
    for key, field in validation.PROTOCOL_FIELDS.items():
        assert validation.FdServerMeta.model_fields[field].alias in (None, key)


class TestSimulator:
    def test_parse_is_case_insensitive(self):
        assert Simulator.parse("powerworld") is Simulator.POWER_WORLD
        assert Simulator.parse("PowerWorld") is Simulator.POWER_WORLD

    def test_parse_returns_none_for_an_unknown_name(self):
        assert Simulator.parse("nope") is None
        assert Simulator.parse("") is None
