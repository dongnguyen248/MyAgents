import json
import re
import unittest
from pathlib import Path

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "contracts.schema.json"
)
ERRORS_PATH = Path(__file__).resolve().parents[2] / "contracts" / "errors.md"

UPPER_SNAKE_CASE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ErrorCodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
            cls.schema = json.load(schema_file)
        cls.valid_categories = set(
            cls.schema["$defs"]["PlatformError"]["properties"]["category"]["enum"]
        )

        with ERRORS_PATH.open(encoding="utf-8") as errors_file:
            cls.errors_content = errors_file.read()

    def parse_table_rows(self):
        rows = []
        for line in self.errors_content.splitlines():
            line = line.strip()
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 4 and cells[0].lower() != "code":
                rows.append({
                    "code": cells[0],
                    "category": cells[1],
                    "retryable": cells[2],
                    "meaning": cells[3],
                })
        return rows

    def test_error_codes_catalog(self):
        rows = self.parse_table_rows()
        self.assertGreaterEqual(len(rows), 18)

        codes = [row["code"] for row in rows]
        # Assert codes are unique
        self.assertEqual(len(codes), len(set(codes)), "Error codes must be unique")

        # Assert table contains NOT_FOUND and APPROVAL_NOT_AUTHORIZED
        self.assertIn("NOT_FOUND", codes)
        self.assertIn("APPROVAL_NOT_AUTHORIZED", codes)
        not_auth_row = next(r for r in rows if r["code"] == "APPROVAL_NOT_AUTHORIZED")
        self.assertEqual(not_auth_row["category"], "APPROVAL")

        for row in rows:
            code = row["code"]
            category = row["category"]
            with self.subTest(code=code):
                # Assert code is UPPER_SNAKE_CASE
                self.assertRegex(
                    code,
                    UPPER_SNAKE_CASE_PATTERN,
                    f"Code {code} must be UPPER_SNAKE_CASE",
                )
                # Assert category is in PlatformError.category enum
                self.assertIn(
                    category,
                    self.valid_categories,
                    f"Category {category} for code {code} must be in PlatformError.category enum",
                )

    def test_meanings_non_empty_and_unique(self):
        rows = self.parse_table_rows()
        meanings = [row["meaning"] for row in rows]
        for row in rows:
            self.assertTrue(row["meaning"].strip(), f"Meaning for {row['code']} is empty")
        self.assertEqual(len(meanings), len(set(meanings)), "Error code meanings must be unique")


if __name__ == "__main__":
    unittest.main()
