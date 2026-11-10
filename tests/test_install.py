"""Install into a relocated Unicode/space path, entirely offline."""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "PowerShell installer is Windows-specific")
    def test_relocated_install_preserves_config_and_copies_runtime(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        with tempfile.TemporaryDirectory(prefix="pet-install-") as temp:
            pet = Path(temp) / "异地 安装" / "pet"
            pet.mkdir(parents=True)
            (pet / "run_server.py").write_text("# fixture\n", encoding="utf-8")
            (pet / "pyproject.toml").write_text(
                '[project]\nversion = "1.2.1"\n', encoding="utf-8"
            )
            command = [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO / "install.ps1"),
                "-PetRoot",
                str(pet),
                "-PythonExe",
                sys.executable,
            ]
            first = subprocess.run(command, cwd=temp, capture_output=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((pet / "bridge/_v0/sender.py").is_file())
            self.assertTrue((pet / "src/open_llm_vtuber/routes.py").is_file())
            config = pet / "bridge/config.json"
            data = json.loads(config.read_text(encoding="utf-8-sig"))
            data["custom"] = "keep"
            config.write_text(json.dumps(data), encoding="utf-8")
            second = subprocess.run(command, cwd=temp, capture_output=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(json.loads(config.read_text())["custom"], "keep")
            snippet = json.loads(
                (pet / "bridge/data/generated/mcp_servers.ready.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            self.assertEqual(
                snippet["mcp_servers"]["msg-bridge"]["command"], sys.executable
            )
            env = dict(
                os.environ,
                PET_CONFIG=str(config),
                PET_DATA_DIR=str(pet / "private data"),
                PYTHONDONTWRITEBYTECODE="1",
            )
            doctor = subprocess.run(
                [sys.executable, str(pet / "bridge/doctor.py")],
                cwd=temp,
                env=env,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            self.assertTrue(json.loads(doctor.stdout)["bundled_helpers"])

    def test_public_docs_have_no_control_characters(self):
        for path in REPO.rglob("*.md"):
            text = path.read_text(encoding="utf-8-sig")
            self.assertFalse(
                [c for c in text if ord(c) < 32 and c not in "\n\r\t"], str(path)
            )

    def test_public_runtime_parses_and_contains_no_author_paths(self):
        for folder in ("bridge", "runtime"):
            for path in (REPO / folder).rglob("*.py"):
                source = path.read_text(encoding="utf-8-sig")
                ast.parse(source, filename=str(path))
                self.assertNotIn("D:" + chr(92) + "project" + chr(92) + "MP", source)
                self.assertNotIn("D:" + chr(92) + "coding" + chr(92) + "python", source)


if __name__ == "__main__":
    unittest.main()
