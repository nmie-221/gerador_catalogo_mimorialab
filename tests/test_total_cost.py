import unittest
from decimal import Decimal

from utils.total_cost import estimate


class TotalCostTests(unittest.TestCase):
    def test_highest_platform_includes_percentage_fixed_and_freight(self):
        result = estimate(10, 50, 5, [
            {"name": "A", "commission": 12, "fixed": 6, "freight": 10},
            {"name": "B", "commission": 20, "fixed": 2, "freight": 1},
        ])
        self.assertEqual(result["platform"], "A")
        self.assertEqual(result["total"], Decimal("37"))
        self.assertEqual(result["profit"], Decimal("13"))

    def test_platform_ranking_depends_on_selling_price(self):
        platforms = [
            {"name": "fixed", "commission": 0, "fixed": 10, "freight": 0},
            {"name": "percent", "commission": 20, "fixed": 0, "freight": 0},
        ]
        self.assertEqual(estimate(0, 20, platforms=platforms)["platform"], "fixed")
        self.assertEqual(estimate(0, 100, platforms=platforms)["platform"], "percent")

    def test_no_platform_and_zero_price(self):
        result = estimate(7, 0, 3)
        self.assertEqual(result["total"], Decimal("10"))
        self.assertEqual(result["margin"], Decimal("0"))

    def test_invalid_commission(self):
        with self.assertRaises(ValueError):
            estimate(1, 10, platforms=[{"name": "X", "commission": 100, "fixed": 0, "freight": 0}])


if __name__ == "__main__":
    unittest.main()
