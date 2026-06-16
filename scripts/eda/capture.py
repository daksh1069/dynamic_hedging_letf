"""
Stdout capture utility — tees print() output to a .txt file.

Usage (in any script's __main__ block):

    from capture import capture_stdout

    if __name__ == "__main__":
        with capture_stdout(OUT_DIR / "results.txt"):
            main()

Every print() inside the block goes to both the terminal AND the file.
The file is overwritten on every run. Any new print() added to main()
is automatically captured — no manual duplication needed.
"""
import io
import sys
from contextlib import contextmanager
from pathlib import Path


class _Tee:
    """Write to both real stdout and an in-memory buffer simultaneously."""

    def __init__(self, real, buf):
        self._real = real
        self._buf = buf

    def write(self, text):
        self._real.write(text)
        self._buf.write(text)

    def flush(self):
        self._real.flush()
        self._buf.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


@contextmanager
def capture_stdout(out_path: Path):
    """Tee stdout to `out_path` while the block runs. Overwrites on every call."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    tee = _Tee(sys.stdout, buf)
    sys.stdout = tee
    try:
        yield
    finally:
        sys.stdout = tee._real
        out_path.write_text(buf.getvalue())
        print(f"[results saved → {out_path}]")
