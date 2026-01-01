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
