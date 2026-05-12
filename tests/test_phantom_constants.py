"""Тесты констант фантомного сотрудника из config.py."""
import pytest


class TestPhantomConstants:

    def test_phantom_id_exists(self):
        from config import PHANTOM_CHECK_FILLING_ID
        assert PHANTOM_CHECK_FILLING_ID is not None

    def test_phantom_id_value(self):
        from config import PHANTOM_CHECK_FILLING_ID
        assert PHANTOM_CHECK_FILLING_ID == 1984002026

    def test_phantom_name_exists(self):
        from config import PHANTOM_CHECK_FILLING_NAME
        assert PHANTOM_CHECK_FILLING_NAME is not None
        assert len(PHANTOM_CHECK_FILLING_NAME) > 0

    def test_phantom_rate_value(self):
        from config import PHANTOM_HOURLY_RATE
        assert PHANTOM_HOURLY_RATE == 1500
