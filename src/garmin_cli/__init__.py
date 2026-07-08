"""garmin-cli — Garmin Connect data extractor."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("garmin-py")
except PackageNotFoundError:  # running from a source tree without installed metadata
    __version__ = "0.0.0+unknown"
