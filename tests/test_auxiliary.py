import unittest
from unittest.mock import patch

import pandas as pd

from repositories import data
from services.google_sheets import HEADERS


class AuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame([
            ["A1", "Primeiro", "PR", "Sim"],
            ["A2", "Segundo", "SG", "Sim"],
        ], columns=["id", "nome", "abreviacao", "ativo"])
        self.products = pd.DataFrame(columns=HEADERS["PRODUTOS"])
        self.reader = patch.object(data, "fresh_table", side_effect=lambda kind: self.products if kind == "produtos" else self.frame)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def test_edit_and_delete_each_domain_use_correct_sheet_and_row(self):
        for kind in data.DOMAIN_PRODUCT_FIELDS:
            with self.subTest(kind=kind), patch.object(data, "update_row") as update, patch.object(data, "delete_row") as delete:
                data.edit_domain(kind, "A2", " Novo nome ", "nv", False)
                update.assert_called_once_with(data.SHEETS[kind], 3, ["A2", "Novo nome", "NV", "Nao"])
                data.delete_domain(kind, "A2")
                delete.assert_called_once_with(data.SHEETS[kind], 3)

    def test_linked_items_can_be_disabled_but_not_deleted_or_reabbreviated(self):
        for kind, field in data.DOMAIN_PRODUCT_FIELDS.items():
            self.products = pd.DataFrame([{field: "A1"}])
            with self.subTest(kind=kind), patch.object(data, "update_row") as update, patch.object(data, "delete_row") as delete:
                data.edit_domain(kind, "A1", "Renomeado", "PR", False)
                update.assert_called_once()
                with self.assertRaises(ValueError):
                    data.edit_domain(kind, "A1", "Renomeado", "XX", True)
                with self.assertRaises(ValueError):
                    data.delete_domain(kind, "A1")
                delete.assert_not_called()

    def test_invalid_or_duplicate_values_never_write(self):
        for name, abbrev in [("", "PR"), (" segundo ", "PR"), ("Novo", "sg"), ("Novo", "ABCDE")]:
            with self.subTest(name=name, abbrev=abbrev), patch.object(data, "update_row") as update:
                with self.assertRaises(ValueError):
                    data.edit_domain("categorias", "A1", name, abbrev, True)
                update.assert_not_called()

    def test_missing_record_never_deletes(self):
        with patch.object(data, "delete_row") as delete:
            with self.assertRaises(ValueError):
                data.delete_domain("categorias", "missing")
            delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
