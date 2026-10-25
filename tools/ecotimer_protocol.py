"""Shim: the protocol lives in the integration (custom_components/kermi_ecotimer/protocol.py)."""

import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "custom_components" / "kermi_ecotimer" / "protocol.py"
_spec = importlib.util.spec_from_file_location("kermi_ecotimer_protocol", _path)
_module = importlib.util.module_from_spec(_spec)
sys.modules["kermi_ecotimer_protocol"] = _module
_spec.loader.exec_module(_module)

globals().update({k: v for k, v in vars(_module).items() if not k.startswith("__")})
schedule_summary = _module.day_summary
