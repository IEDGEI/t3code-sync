"""Build a portable Windows package using an explicit public-file allowlist."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = (
    'Install.cmd', 'install.ps1', 'check-runtime.cjs', 'autosync.py',
    'writer.cjs', 'README.md', 'README.ko.md', '노트북 설치 안내.md', 'github.md',
    'LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/T3-CODE-MIT.txt',
    'docs/RECOVERY.md', 'CONTRIBUTING.md',
)
FOLDER = 'T3-Codex-AutoSync-Windows'


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
            if name == 'Install.cmd':
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            archive.writestr(FOLDER + '/' + name, data)
            checksums.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr(FOLDER + '/SHA256SUMS.txt', '\n'.join(checksums) + '\n')
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(FILES) + 1
        for name in archive.namelist():
            assert not name.endswith(('.sqlite', '.db', '.log', 'config.json'))
    temporary.replace(output)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent / 'SHA256SUMS.txt').write_text(checksum + '  ' + output.name + '\n', encoding='utf-8')
    print(str(output))
    print('Files:', len(FILES) + 1)
    print('Bytes:', output.stat().st_size)
    print('SHA256:', checksum)
    return output


if __name__ == '__main__':
    build()
