import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_rule_catalogue_schema_is_frozen() -> None:
    schema = ROOT / "schemas" / "rule-catalogue.schema.json"
    lock = (ROOT / "schemas" / "SCHEMA.lock").read_text().split()[0]
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == lock


def test_rule_catalogue_schema_is_valid_json_schema() -> None:
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(
        json.loads((ROOT / "schemas" / "rule-catalogue.schema.json").read_text())
    )
