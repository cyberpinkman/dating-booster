import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (
    "agent_adapters",
    "dating_boost",
    "scripts",
    "skills",
    "tests",
)


class SourceTreeHygieneTests(unittest.TestCase):
    def test_no_numbered_python_copy_files(self):
        offenders = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for source_dir in SOURCE_DIRS
            for path in (REPO_ROOT / source_dir).rglob("* 2.py")
            if path.is_file()
        )

        self.assertEqual(
            [],
            offenders,
            "Remove numbered Python copy files; they duplicate modules or tests and pytest collects them.",
        )


if __name__ == "__main__":
    unittest.main()
