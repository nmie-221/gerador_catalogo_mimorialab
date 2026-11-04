import unittest

from utils.sku import build_sku


class SkuGenerationTests(unittest.TestCase):
    def test_generates_sku_in_documented_order(self):
        self.assertEqual(build_sku("P001", "AD", "5X5", "BR", "K2", "VF"), "001AD5X5BRK2VF")

    def test_normalizes_legacy_abbreviations(self):
        self.assertEqual(build_sku("P002", " ád ", " 5 x 5 ", "br", "k2", "vf"), "002AD5X5BRK2VF")

    def test_invalid_abbreviation_identifies_domain(self):
        with self.assertRaisesRegex(ValueError, "material"):
            build_sku("P003", "AD", "5X5", "BR", "K2", "ABCDE")

    def test_missing_abbreviation_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "kit"):
            build_sku("P004", "AD", "5X5", "BR", "", "VF")


if __name__ == "__main__":
    unittest.main()
