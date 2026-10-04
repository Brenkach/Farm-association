import os
import sys
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import OffersService


def make_query(items=None, error=None):
    q = MagicMock()
    if error:
        q.all.side_effect = error
    else:
        q.all.return_value = items or []
    q.first.return_value = None
    return q


def db_error():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_offers_success_without_fallback():
    """Позитивний сценарій: БД працює, fallback не активується."""
    farms = make_query(items=["farm1"])
    specs = make_query(items=["spec1"])
    items = make_query(items=["offer1", "offer2"])

    result = OffersService().get_offers_page_data(farms, specs, None, items)

    assert result["is_fallback"] is False
    assert result["items"] == ["offer1", "offer2"]
    assert farms.all.call_count == 1


def test_offers_fallback_after_3_retries_when_db_down():
    """Resilience: БД недоступна -> рівно 3 спроби -> graceful fallback."""
    farms = make_query(error=db_error())
    specs = make_query()
    items = make_query()

    result = OffersService().get_offers_page_data(farms, specs, None, items)

    assert farms.all.call_count == 3
    assert result["is_fallback"] is True
    assert result["items"] == []
    assert result["farms"] == []
    assert result["current_farm"] is None