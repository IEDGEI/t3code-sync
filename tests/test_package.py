import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_package


class PackageTests(unittest.TestCase):
    def test_only_public_files_and_notices_are_packaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / '한글 경로'
            root.mkdir()
            for name in build_package.FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('public content\n', encoding='utf-8')
            (root / 'config.json').write_text('{"private":true}', encoding='utf-8')
            (root / 'statev2.sqlite').write_bytes(b'private data')
            (root / '노트북 설치 안내.md').write_text('personal guide', encoding='utf-8')
            output_bytes = io.BytesIO()
            console = io.TextIOWrapper(output_bytes, encoding='cp1252')
            with patch.object(build_package, 'ROOT', root), patch('sys.stdout', console):
                output = build_package.build()
            console.flush()
            self.assertIn(b'Files:', output_bytes.getvalue())
            with zipfile.ZipFile(output) as archive:
                expected = {build_package.FOLDER + '/' + build_package.package_name(name)
                            for name in build_package.FILES}
                expected.add(build_package.FOLDER + '/SHA256SUMS.txt')
                self.assertEqual(set(archive.namelist()), expected)
                for line in archive.read(build_package.FOLDER + '/SHA256SUMS.txt').decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(archive.read(build_package.FOLDER + '/' + name)).hexdigest(), digest)
                self.assertIn(build_package.FOLDER + '/LICENSE', expected)
                self.assertIn(build_package.FOLDER + '/licenses/T3-CODE-MIT.txt', expected)
                self.assertNotIn(build_package.FOLDER + '/노트북 설치 안내.md', archive.namelist())
                self.assertEqual(archive.read(build_package.FOLDER + '/Install.cmd'), b'public content\r\n')
            self.assertEqual((output.parent / 'SHA256SUMS.txt').read_text().strip(),
                             hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name)


if __name__ == '__main__':
    unittest.main()
