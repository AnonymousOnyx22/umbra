import unittest
from pathlib import Path
from types import SimpleNamespace

from umbra.tui import Umbra


class NavigationInputTests(unittest.TestCase):
    def _submit(self, value):
        calls = []
        fake = SimpleNamespace(
            prompt=SimpleNamespace(value=value),
            _change_dir=lambda path: calls.append(path),
            _resolve_dir=lambda path: Path('C:/Users/Nick/Downloads/Projects/DiscordForge')
            if path == 'DiscordForge' else None,
            _norm=Umbra._norm,
            run_worker=lambda *_args, **_kwargs: self.fail('sent navigation to the model'),
        )
        event = SimpleNamespace(input=SimpleNamespace(id='prompt'), value=value)
        Umbra.on_input_submitted(fake, event)
        return calls

    def test_typed_cd_changes_app_directory(self):
        self.assertEqual(self._submit('cd C:/Users/Nick/Downloads/Projects/DiscordForge'),
                         ['C:/Users/Nick/Downloads/Projects/DiscordForge'])

    def test_named_project_changes_app_directory(self):
        self.assertEqual(self._submit('DiscordForge'),
                         [str(Path('C:/Users/Nick/Downloads/Projects/DiscordForge'))])


if __name__ == '__main__':
    unittest.main()
