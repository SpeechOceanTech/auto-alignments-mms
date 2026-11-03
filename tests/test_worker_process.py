"""Exercise the real worker boundary without loading a model or needing a GPU."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alignment_web.app import _default_runner


class WorkerProcessTests(unittest.TestCase):
    def test_real_runner_isolated_and_reports_results_and_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Python imports sitecustomize in the child at startup. Supplying a
            # fake core this way exercises actual process creation and IPC.
            (root / 'sitecustomize.py').write_text('''
import json, os, sys, types
from pathlib import Path
core = types.ModuleType("alignment_core")
def align(audio, text, language, output, already_converted=False):
    print("model may print arbitrary messages")
    if language == "fail":
        raise ValueError("diagnostic from alignment")
    if language == "crash":
        os._exit(42)
    output = Path(output)
    (output / "child.json").write_text(json.dumps({
        "pid": os.getpid(), "visible": os.getenv("CUDA_VISIBLE_DEVICES"),
        "device": os.getenv("ALIGN_DEVICE"), "converted": already_converted}))
    result = {}
    for name in ("csv", "txt", "textgrid"):
        path = output / ("alignment." + name)
        path.write_text("result")
        result[name] = path
    return result
core.align = align
sys.modules["alignment_core"] = core
''', encoding='utf-8')
            pythonpath = str(root) + os.pathsep + os.environ.get('PYTHONPATH', '')
            with patch.dict(os.environ, {'PYTHONPATH': pythonpath, 'CUDA_VISIBLE_DEVICES': '0',
                                        'ALIGN_DEVICE': 'cuda:0'}):
                result = _default_runner(root / 'normalized.wav', root / 'input.txt', 'zh_cn', root)
                self.assertEqual(set(result), {'csv', 'txt', 'textgrid'})
                self.assertTrue(all(Path(path).read_text() == 'result' for path in result.values()))
                child = json.loads((root / 'child.json').read_text())
                self.assertNotEqual(child['pid'], os.getpid())
                self.assertEqual((child['visible'], child['device']), ('0', 'cuda:0'))
                self.assertTrue(child['converted'])
                with self.assertRaisesRegex(RuntimeError, 'diagnostic from alignment'):
                    _default_runner(root / 'audio.wav', root / 'input.txt', 'fail', root)
                with self.assertRaisesRegex(RuntimeError, '状态码 42'):
                    _default_runner(root / 'audio.wav', root / 'input.txt', 'crash', root)


if __name__ == '__main__':
    unittest.main()
