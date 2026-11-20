"""Build a portable Windows package using an explicit public-file allowlist."""
import hashlib
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'scripts/Install.cmd', 'scripts/install.ps1', 'scripts/shortcut.ps1',
    'scripts/check-runtime.cjs', 'src/autosync.py', 'src/writer.cjs',
    'README.md', 'README.ko.md', 'LICENSE', 'licenses/T3-CODE-MIT.txt',
    'docs/THIRD_PARTY_NOTICES.md', 'docs/RECOVERY.md', 'docs/CONTRIBUTING.md',
    'docs/github.md',
)
FOLDER = 'T3-Codex-AutoSync-Windows'


def package_name(name):
    # Keep one double-click installer at the top of the extracted ZIP.
    return 'Install.cmd' if name == 'scripts/Install.cmd' else name


def build():
    output = ROOT / 'dist' / (FOLDER + '.zip')
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix('.zip.tmp')
    checksums = []
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = ROOT / name
            if not path.is_file() or path.is_symlink():
                raise ValueError('Required package file is missing: ' + name)
            data = path.read_bytes()
            target = package_name(name)
            if target == 'Install.cmd':
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            archive.writestr(FOLDER + '/' + target, data)
            checksums.append(hashlib.sha256(data).hexdigest() + '  ' + target)
        archive.writestr(FOLDER + '/SHA256SUMS.txt', '\n'.join(checksums) + '\n')
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(FILES) + 1
        for name in archive.namelist():
            assert not name.endswith(('.sqlite', '.db', '.log', 'config.json'))
    temporary.replace(output)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent / 'SHA256SUMS.txt').write_text(checksum + '  ' + output.name + '\n', encoding='utf-8')
    # A redirected English Windows console may not represent a Unicode path.
    encoding = sys.stdout.encoding or 'utf-8'
    print(str(output).encode(encoding, errors='backslashreplace').decode(encoding))
    print('Files:', len(FILES) + 1)
    print('Bytes:', output.stat().st_size)
    print('SHA256:', checksum)
    return output


if __name__ == '__main__':
    build()
