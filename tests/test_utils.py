import pytest
import utils


def test_format_time():
    assert utils.format_time(3661.456) == "01:01:01.456"
    assert utils.format_time(3661.456, "mm:ss.sss") == "61:01.456"
    assert utils.format_time(3661.456, "hh-mm-ss.sss") == "01-01-01.456"
    assert utils.format_time(3661.456, "mm-ss.sss") == "61-01.456"
    assert utils.format_time(3661.456, "ss.sss") == "3661.456"
    assert utils.format_time(3661.456, "hhmmss.sss") == "010101.456"
    with pytest.raises(ValueError):
        utils.format_time(3661.456, "invalid_format")

def test_time_str_to_sec():
    assert utils.time_str_to_sec("01:01:01.456") == 3661.456
    assert utils.time_str_to_sec("61:01.456") == 3661.456
    assert utils.time_str_to_sec("3661.456") == 3661.456
    with pytest.raises(ValueError):
        utils.time_str_to_sec("invalid_time")

def test_simple_cache():
    cache = utils.SimpleCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert cache.get("b") is None  # "b" should be evicted
    assert cache.get("c") == 3
    
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("c") is None
    
def test_simple_cache_unlimited():
    cache = utils.SimpleCache(max_size=0)  # Unlimited size
    for i in range(100):
        cache.set(f"key{i}", i)
    for i in range(100):
        assert cache.get(f"key{i}") == i

