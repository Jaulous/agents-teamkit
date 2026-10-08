# Vendored Dependencies

TeamKit runtime packages (for example WorkBuddy plugins) must run on a host
without network access or `pip`. The packages below are vendored so the
runtime only needs a Python 3.10+ interpreter.

| Package | Version | License | Local changes |
|---|---|---|---|
| PyYAML (pure-Python) | 6.0.3 | MIT (`yaml/LICENSE`) | `cyaml.py` removed and the libyaml import in `__init__.py` disabled |

TeamKit prefers an installed `PyYAML` when one is importable and falls back to
this copy otherwise.
