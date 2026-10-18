import pytest

from phenix_apps.common import utils
from phenix_apps.common.error import AppError


def test_connect_elastic_raises_instead_of_exiting(monkeypatch):
    closed = []

    class EmptyES:
        def __init__(self, url):
            pass

        def info(self):
            return {}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(utils, "Elasticsearch", EmptyES)

    with pytest.raises(AppError, match="http://es:9200 returned no cluster info"):
        utils.connect_elastic("http://es:9200")
    assert closed == [True]
