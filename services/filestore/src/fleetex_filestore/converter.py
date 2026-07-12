"""Image conversion — port of FileConverter.js + ImageOptimiser.js.

NOTE: this shells out to ImageMagick ``convert`` (or ``pdftocairo``) then
``optipng``, exactly like the Node original. It is implemented for parity but is
UNVERIFIED in Fleetex CI (those binaries aren't installed here). Only ``png``
output is supported. A missing binary or a conversion failure raises
``ConversionError`` -> HTTP 500, matching the Node behavior.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile

from .errors import ConversionError

APPROVED_FORMATS = ["png"]
_CONVERT_TIMEOUT = 40
_OPTIPNG_TIMEOUT = 30

# ImageMagick geometry per style (FileConverter.js).
_STYLE_SIZE = {"thumbnail": "260x", "preview": "1000", None: "600x"}


def _run(cmd: list[str], timeout: int) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ConversionError(f"converter binary not found: {cmd[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"conversion failed: {exc}") from exc


def convert_to_png(source_path: str, fmt: str | None, style: str | None, converter: str = "imagemagick") -> str:
    """Convert ``source_path`` to a PNG and return the output path."""
    if fmt is not None and fmt not in APPROVED_FORMATS:
        raise ConversionError(f"invalid format {fmt!r} (only png)")
    if style is not None and style not in ("thumbnail", "preview"):
        raise ConversionError(f"invalid style {style!r}")

    out_path = tempfile.mkstemp(suffix=".png")[1]
    if converter == "imagemagick":
        size = _STYLE_SIZE.get(style, _STYLE_SIZE[None])
        _run(["convert", "-density", "300", "-flatten", "-resize", size, f"{source_path}[0]", out_path], _CONVERT_TIMEOUT)
    else:  # pdftocairo
        width = {"thumbnail": "700", "preview": "1000"}.get(style, "1500")
        _run(["pdftocairo", "-png", "-singlefile", "-scale-to-x", width, "-scale-to-y", "-1", source_path, out_path[:-4]], _CONVERT_TIMEOUT)

    if shutil.which("optipng"):
        try:
            _run(["optipng", out_path], _OPTIPNG_TIMEOUT)
        except ConversionError:
            pass  # optipng failure is tolerated (SIGKILL-safe in the original)
    return out_path
