"""Regressions for reading a player's effective appearance resources."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import npc_mod_sources as sources


class ProfileOverlayTests(unittest.TestCase):
    def test_divine_error_is_a_failure_even_on_a_success_exit(self):
        for stdout, stderr in [("[ERROR] Invalid package", ""), ("", "[FATAL] Could not open archive")]:
            with self.subTest(stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr)
                with patch.object(sources.subprocess, "run", return_value=result):
                    with self.assertRaisesRegex(ValueError, "Divine failed"):
                        sources._command("Divine", "-a", "list-package")

    def test_explicit_order_is_respected_and_retains_the_builtin_module(self):
        guid = lambda number: f"00000000-0000-4000-8000-{number:012d}"
        modules = "".join(
            f'<node id="ModuleShortDesc"><attribute id="UUID" value="{guid(i)}"/>'
            f'<attribute id="Folder" value="{folder}"/></node>'
            for i, folder in enumerate(["GustavX", "FaceA", "FaceB"], start=1)
        )
        order = "".join(f'<node id="Module"><attribute id="UUID" value="{guid(i)}"/></node>'
                        for i in [3, 2])
        settings = (f'<save><region id="ModuleSettings"><node id="root"><children>'
                    f'<node id="Mods"><children>{modules}</children></node>'
                    f'<node id="ModOrder"><children>{order}</children></node>'
                    '</children></node></region></save>')
        self.assertEqual(list(sources._enabled(settings).values()), ["gustavx", "faceb", "facea"])
