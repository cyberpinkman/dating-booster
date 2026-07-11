import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_native_gui_implementation_is_owned_by_harness_package(self):
        implementation = ROOT / "dating_boost" / "harness" / "native_gui.py"
        compatibility = ROOT / "dating_boost" / "core" / "gui_harness.py"

        self.assertTrue(implementation.is_file())
        self.assertFalse(_implementation_definitions(compatibility), compatibility)
        self.assertTrue(any(node.name == "NativeGuiHarness" for node in ast.walk(_tree(implementation)) if isinstance(node, ast.ClassDef)))

    def test_tashuo_release_implementations_are_owned_by_tashuo_app_package(self):
        mapping = {
            "tashuo_stage_beta.py": "stage_beta.py",
            "tashuo_standalone_alpha_gate.py": "standalone_alpha_gate.py",
            "tashuo_stage_alpha_safety.py": "stage_alpha_safety.py",
            "tashuo_stage_alpha_evidence.py": "stage_alpha_evidence.py",
            "tashuo_stage_alpha_utils.py": "stage_alpha_utils.py",
            "tashuo_stage_alpha_release_gate.py": "stage_alpha_release_gate.py",
        }

        for compatibility_name, implementation_name in mapping.items():
            with self.subTest(module=compatibility_name):
                compatibility = ROOT / "dating_boost" / "core" / compatibility_name
                implementation = ROOT / "dating_boost" / "apps" / "tashuo" / implementation_name
                self.assertTrue(implementation.is_file())
                self.assertFalse(_implementation_definitions(compatibility), compatibility)
                self.assertTrue(_implementation_definitions(implementation), implementation)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _implementation_definitions(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


if __name__ == "__main__":
    unittest.main()
