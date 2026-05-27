import ast
from pathlib import Path
import unittest
from types import SimpleNamespace

import run_bot


class CallbackSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config = run_bot.config

    def tearDown(self) -> None:
        run_bot.config = self.original_config

    def test_rejects_callback_when_secret_is_configured_and_missing(self) -> None:
        run_bot.config = SimpleNamespace(callback_secret="secret")

        response = run_bot.app.test_client().post("/", json={"post_type": "meta_event"})

        self.assertEqual(response.status_code, 403)

    def test_allows_callback_when_secret_matches_authorization_header(self) -> None:
        run_bot.config = SimpleNamespace(callback_secret="secret")

        response = run_bot.app.test_client().post(
            "/",
            json={"post_type": "meta_event"},
            headers={"Authorization": "Bearer secret"},
        )

        self.assertEqual(response.status_code, 200)


class DeepSeekConnectivityScriptTests(unittest.TestCase):
    def test_deepseek_connectivity_check_does_not_post_on_import(self) -> None:
        script_path = Path(__file__).resolve().parent / "test_deepseek.py"
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        top_level_posts = []
        has_main = False
        has_main_guard = False

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                has_main = True
            if isinstance(node, ast.If):
                condition = ast.unparse(node.test)
                if "__name__" in condition and "__main__" in condition:
                    has_main_guard = True
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "requests"
                    and child.func.attr == "post"
                    and isinstance(node, ast.Assign)
                ):
                    top_level_posts.append(child)

        self.assertTrue(has_main)
        self.assertTrue(has_main_guard)
        self.assertFalse(top_level_posts)


if __name__ == "__main__":
    unittest.main()
