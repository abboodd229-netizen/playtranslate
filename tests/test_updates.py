from playtranslate.updates import is_newer, parse_version


def test_version_compare():
    assert parse_version("v0.2.0") == (0, 2, 0)
    assert is_newer("v0.2.0", "0.1.1")
    assert is_newer("0.1.10", "0.1.9")
    assert not is_newer("v0.1.1", "0.1.1")
    assert not is_newer("v0.1", "0.1.0")
    assert not is_newer("nightly", "0.1.0")
