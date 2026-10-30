import pathlib, sys

def test_probe():
    out = pathlib.Path(__file__).with_name('probe_out.txt')
    out.write_text(f"cwd={pathlib.Path.cwd()}\nargv={sys.argv}\n", encoding='utf-8')
    assert out.exists()
