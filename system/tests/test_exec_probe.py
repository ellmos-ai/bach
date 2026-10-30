import pathlib

def test_exec_probe(tmp_path):
    marker = pathlib.Path(__file__).resolve().parent / "probe_marker"
    marker.write_text("executed")
    assert True
