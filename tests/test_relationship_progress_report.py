import tempfile
import unittest
from pathlib import Path

from dating_boost.core.relationship_report import build_relationship_progress_report


class RelationshipProgressReportTests(unittest.TestCase):
    def test_build_relationship_progress_report_reads_human_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            human_path = data_dir / "automation" / "reports" / "human_latest.md"
            human_path.parent.mkdir(parents=True)
            human_path.write_text("# Progress Report\n\n## Conversation Plans\n\n## Next Priority Queue\n", encoding="utf-8")

            report = build_relationship_progress_report(
                data_dir=data_dir,
                human_report_path=Path("automation") / "reports" / "human_latest.md",
                machine_report_path=Path("automation") / "reports" / "machine_latest.json",
                summary={"action_result_count": 1},
            )

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["report_type"], "relationship_progress")
        self.assertEqual(report["format"], "markdown")
        self.assertIn("Conversation Plans", report["markdown"])
        self.assertIn("Next Priority Queue", report["markdown"])
        self.assertEqual(report["summary"], {"action_result_count": 1})
        self.assertEqual(report["next_host_action"], "present_relationship_progress_report")


if __name__ == "__main__":
    unittest.main()
