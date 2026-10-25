import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from repositories.data import _money_series
from services import google_sheets
from utils.validators import number


class MoneyTests(unittest.TestCase):
    def test_real_values_and_decimal_comma(self):
        values = ["12,92", "8,3", "8,53", "1.292,00", 1292, 100, 18, 0, "12.92"]
        expected = [12.92, 8.3, 8.53, 1292, 1292, 100, 18, 0, 12.92]
        self.assertEqual([number(v, "Valor") for v in values], expected)
        self.assertEqual(_money_series(pd.Series(values)).tolist(), expected)

    def test_read_preserves_numeric_values_and_barcode(self):
        worksheet = Mock()
        worksheet.get_all_records.return_value = [{"preco": 12.92, "custo": 8.3, "codigo_barras": "00123"}]
        google_sheets.read_sheet.clear()
        try:
            with patch.object(google_sheets, "_worksheet", return_value=worksheet):
                frame = google_sheets.read_sheet("PRODUTOS")
            worksheet.get_all_records.assert_called_once_with(value_render_option="UNFORMATTED_VALUE", numericise_ignore=["all"])
            self.assertEqual(frame.iloc[0]["preco"], 12.92)
            self.assertEqual(frame.iloc[0]["codigo_barras"], "00123")
        finally:
            google_sheets.read_sheet.clear()

    def test_edit_form_amounts_and_switching_products(self):
        products = pd.DataFrame([
            ["P001", "Primeiro", "A1", "A1", "A1", "A1", 12.92, 8.3, "A1", "SKU1", "", ""],
            ["P002", "Segundo", "A1", "A1", "A1", "A1", 1292, 100, "A1", "SKU2", "", ""],
        ], columns=google_sheets.HEADERS["PRODUTOS"])

        def sheet(name):
            if name == "PRODUTOS":
                return products
            return pd.DataFrame([["A1", "Opção", "OP", "Sim"]], columns=google_sheets.HEADERS[name])

        with patch("repositories.data.read_sheet", side_effect=sheet):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.session_state["authenticated"] = True
            app.session_state["page"] = "⚙️ Editar ou excluir"
            app.run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key="edit_product_P001_price").value, "12.92")
            self.assertEqual(app.text_input(key="edit_product_P001_cost").value, "8.30")
            app.selectbox(key="edit_selected_product").select("Segundo (P002)").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key="edit_product_P002_price").value, "1292.00")
            self.assertEqual(app.text_input(key="edit_product_P002_cost").value, "100.00")


if __name__ == "__main__":
    unittest.main()
