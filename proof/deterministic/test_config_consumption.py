import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = (ROOT / "proof" / "reports" / "config-consumption.md").read_text(encoding="utf-8")


def _keys(value: dict, prefix: str = "") -> list[str]:
    result: list[str] = []
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.extend(_keys(child, name))
        else:
            result.append(name)
    return result


def test_every_declared_config_key_is_in_the_consumption_audit():
    for path in sorted((ROOT / "src" / "second_brain" / "defaults" / "config").glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in _keys(data):
            assert f"{path.name} | {key} |" in REPORT, (path.name, key)
