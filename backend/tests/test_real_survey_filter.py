import unittest

from scripts.parse_real_survey import anonymise_participant_id, parse_q20_numeric, q20_validity


class RealSurveyFilterTest(unittest.TestCase):
    def test_q20_accepts_numeric_and_human_written_scores(self) -> None:
        self.assertEqual(parse_q20_numeric("4"), 4)
        self.assertEqual(parse_q20_numeric("8分"), 8)
        self.assertEqual(parse_q20_numeric("我打四分"), 4)
        self.assertEqual(q20_validity("七分"), "VALID")

    def test_q20_rejects_out_of_range_values(self) -> None:
        for value in ("30", "70", "80"):
            self.assertEqual(q20_validity(value), "OUT_OF_RANGE")

    def test_source_ids_are_not_copied_to_derived_records(self) -> None:
        opaque = anonymise_participant_id("WR31BwJ5VlP")
        self.assertTrue(opaque.startswith("real_"))
        self.assertNotIn("WR31BwJ5VlP", opaque)


if __name__ == "__main__":
    unittest.main()
