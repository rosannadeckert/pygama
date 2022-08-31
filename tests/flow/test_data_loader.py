import json
from pathlib import Path

import pandas as pd
import pytest

from pygama import lgdo
from pygama.flow import DataLoader

config_dir = Path(__file__).parent / "configs"


@pytest.fixture(scope="function")
def test_dl(lgnd_test_data):
    with open(config_dir / "filedb-config.json") as f:
        db_config = json.load(f)

    db_config["data_dir"] = lgnd_test_data.get_path("lh5/prod-ref-l200/generated/tier")

    return DataLoader(f"{config_dir}/data-loader-config.json", db_config)


def test_init(test_filedb):
    pass


def test_simple_load(test_dl):
    test_dl.set_files("all")
    test_dl.set_output(columns=["timestamp"])
    data = test_dl.load()

    assert isinstance(data, dict)
    assert isinstance(data[0], lgdo.Table)
    assert len(data) == 2
    assert list(data[0].keys()) == ["hit_table", "hit_idx", "timestamp"]


def test_outputs(test_dl):
    test_dl.set_files("all")
    test_dl.set_output(fmt="pd.DataFrame", columns=["timestamp", "channel"])
    data = test_dl.load()

    assert isinstance(data, dict)
    assert isinstance(data[0], pd.DataFrame)
    assert len(data) == 2
    assert list(data[0].keys()) == ["hit_table", "hit_idx", "timestamp", "channel"]


def test_set_files(test_dl):
    test_dl.set_files("timestamp == '20220716T104550Z'")
    test_dl.set_output(columns=["timestamp"])
    data = test_dl.load()

    assert len(data) == 1


def test_set_datastreams(test_dl):
    test_dl.set_files("all")
    test_dl.set_datastreams([1, 3, 8], "ch")
    test_dl.set_output(columns=["channel"])
    data = test_dl.load()

    assert (data[0]["hit_table"].nda == [1, 3, 8]).all()
    assert (data[0]["channel"].nda == [1, 3, 8]).all()


def test_set_cuts(test_dl):
    test_dl.set_files("all")
    test_dl.set_cuts({"hit": "card == 3"})
    test_dl.set_output(columns=["card"])
    data = test_dl.load()

    assert (data[0]["hit_table"].nda == [12, 13]).all()
