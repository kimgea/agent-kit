def validate_manifest(value):
    return set(value) == {"name", "version"} and isinstance(value["version"], int)


def test_manifest_schema():
    assert validate_manifest({"name": "sample", "version": 1})
    assert not validate_manifest({"name": "sample"})
    assert not validate_manifest({"name": "sample", "version": "1"})
