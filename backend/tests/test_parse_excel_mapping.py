import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from scripts.parse_excel import parse_workbook


class ParseExcelMappingTest(unittest.TestCase):
    def test_source_question_codes_map_to_their_actual_rubric_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["作答ID", "作答总时长", "省份", "城市", "性别", "年龄", "题目"])
            sheet.append(["作答ID", "作答总时长", "省份", "城市", "Q", "Q", "A1", None, "原因", "B5", None, "原因", "E8", None, "原因"])
            sheet.append(["p1", "1", "", "", "", "", "A1回答", 0, "理由", "8", 1, "理由", "责任", 1, "理由"])
            workbook.save(source)

            records = parse_workbook(source)

        by_code = {record["source_question_code"]: record for record in records}
        self.assertEqual(by_code["A1"]["question_id"], "Q09")
        self.assertEqual(by_code["B5"]["question_id"], "Q20")
        self.assertEqual(by_code["E8"]["question_id"], "Q16")


if __name__ == "__main__":
    unittest.main()
