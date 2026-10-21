from types import SimpleNamespace

import pytest

from phenix_apps.apps.scorch.collector.collector import Collector


@pytest.mark.parametrize("annotations", [{}, {"topology": "t"}, {"scenario": "s"}])
def test_stop_names_missing_topology_or_scenario_annotations(tmp_path, annotations):
    collector = SimpleNamespace(
        name="c",
        results_dir=tmp_path / "results",
        meta_dir=tmp_path / "meta",
        get_annotation=annotations.get,
        # Present once the disruption metadata model lands; unused before it.
        _disruption_metadata=lambda: {},
    )

    with pytest.raises(ValueError, match="must name its topology and scenario"):
        Collector.stop(collector)
