#!/usr/bin/env python3
"""Update recommended_stock from input_stock_recommendation.

Usage:
    uv run python scripts/update_recommended_stock.py
    uv run python scripts/update_recommended_stock.py --stock-id 123
"""

import argparse
import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update recommended_stock table from input_stock_recommendation table."
    )
    parser.add_argument(
        "--stock-id",
        type=int,
        default=None,
        help="Optional stock_id to update only one stock. If omitted, updates all stocks.",
    )
    args = parser.parse_args()

    db = RecommendationsDatabase()

    try:
        upserted_count = db.upsert_recommended_stock_from_input(stock_id=args.stock_id)

        if args.stock_id is not None:
            print(
                f"Updated recommended_stock for stock_id={args.stock_id}. "
                f"Rows upserted: {upserted_count}."
            )
        else:
            print(
                "Updated recommended_stock from input_stock_recommendation "
                f"for all stocks. Rows upserted: {upserted_count}."
            )

        return 0
    except Exception as exc:
        print(f"Failed to update recommended_stock: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
