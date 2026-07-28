"""Local catalog tool unit tests — pure SQLite reads, no network, no stubbing.

The seeded fixture data lives in ``src.store.seed``; ``_isolated_db`` (in
conftest) re-seeds it fresh into a temp file for every test.
"""

from __future__ import annotations

from src.store.catalog import check_order_status, get_product_details, search_catalog


def test_check_order_status_returns_seeded_fields():
    result = check_order_status("3")
    assert result["order_id"] == 3
    assert result["status"] == "processing"
    assert result["customer_name"] == "R. Pereira"
    assert len(result["items"]) >= 1


def test_check_order_status_not_found():
    assert check_order_status("999")["error"] == "order_not_found"


def test_check_order_status_invalid_id():
    assert check_order_status("abc")["error"] == "invalid_order_id"


def test_returned_order_supports_the_refund_category():
    """Order 5 is seeded in `returned` status — a real backing record for refunds."""
    result = check_order_status("5")
    assert result["status"] == "returned"


def test_get_product_details():
    result = get_product_details("1")
    assert result["title"] == "Trailhead 45L Backpack"
    assert result["category"] == "outdoor"


def test_get_product_details_not_found():
    assert get_product_details("999")["error"] == "product_not_found"


def test_search_catalog_filters_by_query():
    # "backpack" also substring-matches the tent's "backpacking" description —
    # a plain LIKE search, not exact-word matching, so both are expected.
    result = search_catalog(query="backpack")
    titles = {r["title"] for r in result["results"]}
    assert "Trailhead 45L Backpack" in titles
    assert result["count"] == 2


def test_search_catalog_exact_title_match():
    result = search_catalog(query="Trailhead")
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Trailhead 45L Backpack"


def test_search_catalog_filters_by_category():
    result = search_catalog(query="", category="apparel")
    titles = {r["title"] for r in result["results"]}
    assert "Basecamp Fleece Pullover" in titles
    assert all(r["category"] == "apparel" for r in result["results"])
