import csv
import io
import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import lxml.etree as ET
import pytest
import yaml

from phenix_apps.apps.scale.app import Scale
from phenix_apps.common import settings


@pytest.mark.parametrize(("turbines", "density"), [(1, 6), (3, 12)])
def test_profile_generates_real_artifacts(tmp_path, monkeypatch, turbines, density):
    experiment = yaml.safe_load(
        Path(__file__).with_name("test_wind_turbine_input.yaml").read_text()
    )
    profile = experiment["spec"]["scenario"]["apps"][0]["metadata"]["profiles"][0]
    profile["count"] = turbines
    profile["containers_per_node"] = density
    profile["container_template"]["external_network"][0].pop("gateway")
    profile["ground-truth-module"]["elastic"]["endpoint"] = (
        "http://192.168.100.250:9200"
    )
    templates = profile["templates"]["default"]
    flow = tmp_path / "flow.json"
    flow.write_text('[{"id": "test-flow", "type": "tab", "label": "Test"}]')
    templates["main-controller"]["node-red"] = {"flow": str(flow)}
    weather = tmp_path / "weather.csv"
    columns = templates["anemometer"]["weather"]["columns"]
    with weather.open("w") as file:
        writer = csv.writer(file)
        writer.writerow([column["name"] for column in columns])
        writer.writerow([1] * len(columns))
    templates["anemometer"]["weather"]["replayData"] = str(weather)
    rootfs = tmp_path / "otsimfs.tgz"
    with tarfile.open(rootfs, "w:gz"):
        pass
    profile["container_template"]["rootfs_source"] = str(rootfs)
    experiment["metadata"] = {"annotations": {"retained": "yes"}}
    experiment["spec"]["experimentName"] = "wind-turbine-scale"
    experiment["spec"]["baseDir"] = str(tmp_path / "experiment")
    experiment["spec"]["topology"]["nodes"] = [
        {"general": {"hostname": "existing-node"}}
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(experiment)))
    monkeypatch.setattr(settings, "PHENIX_DIR", str(tmp_path))
    app = Scale("scale", "configure")
    app.configure()
    assert app.experiment.metadata.annotations.retained == "yes"
    assert app.experiment.spec.topology.nodes[0].general.hostname == "existing-node"
    nodes = app.experiment.spec.topology.nodes[1:]
    assert len(nodes) == (turbines * 6 + density - 1) // density

    xml_files = sorted(app.app_dir.glob("wtg-*/*/config.xml"))
    assert len(xml_files) == turbines * 6
    for path in xml_files:
        xml = ET.parse(path)
        assert xml.getroot().tag == "ot-sim"
        assert xml.findtext("ground-truth/elastic/endpoint") == (
            "http://192.168.100.250:9200"
        )
        assert xml.findtext("ground-truth/elastic/label") in {
            f"wtg-{i}" for i in range(1, turbines + 1)
        }
        if xml.find("node-red") is not None:
            assert xml.findtext("node-red/flow-path") == "/etc/ot-sim/node-red.json"
            assert (path.parent / "node-red.json").read_bytes() == flow.read_bytes()
            assert len(xml.findall("modbus")) == 5
            assert xml.find("dnp3") is not None
            assert xml.find("wind-turbine/power-output") is not None
        if xml.find("wind-turbine/anemometer") is not None:
            assert xml.findtext("wind-turbine/anemometer/data-path") == (
                "/shared/weather.csv"
            )
            assert {
                column.get("name")
                for column in xml.findall("wind-turbine/anemometer/weather-data/column")
            } == {column["name"] for column in columns}

    with tarfile.open(Path(app.exp_dir) / "wind-configs.tgz") as archive:
        names = archive.getnames()
        assert sum(name.endswith("/config.xml") for name in names) == turbines * 6
        assert sum(name.endswith("/node-red.json") for name in names) == turbines
    for node in nodes:
        injections = {item.dst: item.src for item in node.injections}
        assert injections["/scale/shared/otsimfs.tgz"] == str(rootfs)
        assert injections["/scale/shared/weather.csv"] == str(weather)
        assert "/wind-configs.tgz" in injections

    # Re-initialize from serialized output, as core does for each lifecycle stage.
    monkeypatch.setattr("sys.stdin", io.StringIO(app.experiment.to_json()))
    post_start = Scale("scale", "post-start")
    mm = MagicMock()
    monkeypatch.setattr("minimega.connect", lambda **kwargs: mm)
    post_start.post_start()
    assert mm.cc_send.call_count == len(nodes)
    scripts = [path.read_text() for path in sorted(post_start.files_dir.glob("*.mm"))]
    assert (
        sum(script.count("vm launch container ") for script in scripts) == turbines * 6
    )
    for script in scripts:
        assert "namespace wind" in script
        assert "vm config filesystem tar:/scale/shared/otsimfs.tgz" in script
        assert "vm config volume /shared/ /scale/shared/" in script
        assert "vm config net wind-turbine-scale,200 wtg-" in script
        assert "vm config volume /etc/ot-sim/ /scale/wtg-" in script
    joined = "\n".join(scripts)
    for i in range(1, turbines + 1):
        assert f"cc exec ip addr add 192.168.100.{9 + i}/24 dev veth0" in joined
        for component in (
            "main-controller",
            "signal-converter",
            "yaw-controller",
            "blade-1",
            "blade-2",
            "blade-3",
        ):
            assert joined.count(f"vm launch container wtg-{i}-{component}\n") == 1
