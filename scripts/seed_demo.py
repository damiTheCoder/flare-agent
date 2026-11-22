"""Seed the demo tenant used by the DSH-style UI (mock provider path)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))

from tools_gateway.accounting import store  # noqa: E402

COMPANY = "acme"


def main() -> None:
    store.resolve_tenant(COMPANY)
    if store.get_customer(COMPANY, "cus_demo") is None:
        store.insert_row(
            "customers",
            {
                "id": "cus_demo",
                "company_id": COMPANY,
                "name": "Adeshina",
                "email": "adeshina@example.com",
                "phone": None,
            },
        )
    if store.get_item(COMPANY, "itm_demo") is None:
        store.insert_row(
            "items",
            {
                "id": "itm_demo",
                "company_id": COMPANY,
                "name": "Ankara Fabric",
                "sku": "ANK-001",
                "price": "250.00",
                "cost": "120.00",
                "stock_quantity": 50,
            },
        )
    print(f"seeded tenant {COMPANY}: customer cus_demo, item itm_demo")


if __name__ == "__main__":
    main()
