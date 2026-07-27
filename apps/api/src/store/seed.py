"""Fixture data for the in-house "Basecamp Supply Co." catalog.

Replaces a call out to a public demo API: the whole commerce backend the
Researcher node queries is a handful of local SQLite tables, seeded once at
startup. That keeps the entire pipeline runnable with zero network egress
other than the LLM provider itself, and — unlike a modulo-derived synthetic
status — every order below has a real ``status`` column, including one seeded
in ``returned`` so the refund category has an actual backing record.
"""

from __future__ import annotations

import sqlite3

PRODUCTS: list[tuple[int, str, str, float, str]] = [
    # id, title, category, price, description
    (1, "Trailhead 45L Backpack", "outdoor", 129.99, "Weatherproof multi-day hiking pack."),
    (2, "Summit Ridge 2-Person Tent", "outdoor", 189.50, "Freestanding 3-season backpacking tent."),
    (3, "EmberCore Camp Stove", "outdoor", 54.00, "Compact folding stove, isobutane canister."),
    (4, "AquaFlow Filter Bottle", "outdoor", 32.75, "0.2-micron filter straw built into the cap."),
    (5, "NightSky 4-Season Sleeping Bag", "outdoor", 145.00, "Rated to -6C, synthetic fill."),
    (6, "TrailBeam Headlamp 400", "electronics", 28.99, "400-lumen rechargeable headlamp."),
    (7, "PowerCell 10K Solar Charger", "electronics", 45.50, "10,000mAh panel-charged power bank."),
    (8, "RangeFinder GPS Compass", "electronics", 62.00, "Handheld GPS unit with digital compass."),
    (9, "WeatherEye Handheld Anemometer", "electronics", 39.99, "Wind speed/temperature meter."),
    (10, "Basecamp Fleece Pullover", "apparel", 58.00, "Midweight fleece, half-zip."),
    (11, "TrailGuard Rain Shell", "apparel", 89.00, "Packable waterproof-breathable shell."),
    (12, "Summit Wool Hiking Socks (3-pack)", "apparel", 18.50, "Merino blend, cushioned sole."),
]

# id, customer_name, status, carrier, tracking_number, placed_at
ORDERS: list[tuple[int, str, str, str | None, str | None, str]] = [
    (1, "J. Alvarez", "delivered", "UPS", "1Z999AA10123456784", "2026-07-01"),
    (2, "M. Chen", "in_transit", "FedEx", "784123456789", "2026-07-10"),
    (3, "R. Fontaine", "processing", None, None, "2026-07-20"),
    (4, "S. Okafor", "shipped", "USPS", "9400111899223197428506", "2026-07-15"),
    (5, "K. Patel", "returned", "UPS", "1Z999AA10123456785", "2026-06-25"),
    (6, "D. Nguyen", "delivered", "FedEx", "784123456790", "2026-06-18"),
    (7, "L. Torres", "in_transit", "UPS", "1Z999AA10123456786", "2026-07-22"),
    (8, "A. Kessler", "processing", None, None, "2026-07-24"),
    (9, "E. Whitfield", "delivered", "USPS", "9400111899223197428507", "2026-06-05"),
    (10, "P. Yamamoto", "shipped", "FedEx", "784123456792", "2026-07-18"),
]

# order_id, product_id, quantity
ORDER_ITEMS: list[tuple[int, int, int]] = [
    (1, 1, 1),
    (1, 6, 1),
    (2, 2, 1),
    (3, 3, 2),
    (3, 4, 1),
    (4, 5, 1),
    (5, 11, 1),
    (6, 7, 1),
    (6, 9, 1),
    (7, 8, 1),
    (8, 10, 1),
    (8, 12, 2),
    (9, 1, 1),
    (9, 5, 1),
    (10, 6, 2),
    (10, 4, 1),
]


def seed_catalog(conn: sqlite3.Connection) -> None:
    """Idempotently load the fixture catalog. Safe to call on every startup."""
    conn.executemany(
        "INSERT OR IGNORE INTO products (id, title, category, price, description) "
        "VALUES (?, ?, ?, ?, ?)",
        PRODUCTS,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO orders (id, customer_name, status, carrier, "
        "tracking_number, placed_at) VALUES (?, ?, ?, ?, ?, ?)",
        ORDERS,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)",
        ORDER_ITEMS,
    )
    conn.commit()
