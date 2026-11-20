"""Portable Windows installer checks. All writes stay in an isolated temp folder."""
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import autosync
import build_package

SOURCE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows installer')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='t3-laptop-')
        # Hosted Windows runners may expose TEMP using an 8.3 alias. Compare
        # canonical paths, as PowerShell expands that alias while installing.
        self.root = Path(self.temp.name).resolve() / '노트북 설치 폴더'
        self.source = self.root / 'package'
        self.home = self.root / 'T3 data'
        self.codex = self.root / 'Codex data'
        self.install = self.root / 'installed'
        self.shortcuts = self.root / 'Desktop'
        self.exe = self.root / 'T3 app' / 'T3 Code (Beta).exe'
        self.db = self.home / 'userdata' / 'statev2.sqlite'
        for folder in (self.source, self.shortcuts, self.codex, self.exe.parent, self.db.parent, self.home / 'bin'):
            folder.mkdir(parents=True, exist_ok=True)
        self.exe.write_bytes(b'not executed by installer tests')
        for name in build_package.FILES:
            (self.source / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / name, self.source / name)
        subprocess.run(['node', '--disable-warning=ExperimentalWarning', '-e',
            "new(require('node:sqlite').DatabaseSync)(process.argv[1]).exec(require('node:fs').readFileSync(process.argv[2],'utf8'))",
            str(self.db), str(SOURCE / 'tests/schema_fixture.sql')], check=True, capture_output=True)
        with sqlite3.connect(str(self.codex / 'state_5.sqlite'), factory=autosync.ClosingConnection) as db:
            db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT)')
        with autosync.readonly(self.db) as db:
            digest = autosync.schema_digest(db)
        # Recreating CREATE statements can normalize their SQL formatting. Pin
        # this synthetic fixture's digest in the isolated test package only.
        text = (SOURCE / 'src/autosync.py').read_text(encoding='utf-8')
        text = re.sub(r'SUPPORTED_SCHEMA = "[0-9a-f]+"', 'SUPPORTED_SCHEMA = "' + digest + '"', text)
        (self.source / 'src/autosync.py').write_text(text, encoding='utf-8')
        (self.home / 'bin' / 't3.cmd').write_text('if exist "' + str(self.exe) + '" goto run\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *extra, use_cmd=False, skip_existing=True):
        # Windows PowerShell 5.1 is what Install.cmd uses on a normal laptop.
        arguments = ['-T3Home', str(self.home), '-CodexHome', str(self.codex),
            '-InstallDir', str(self.install), '-ShortcutDir', str(self.shortcuts),
            '-PythonExe', sys.executable, '-NodeExe', shutil.which('node.exe')] + list(extra)
        if skip_existing:
            arguments.append('-SkipExistingShortcuts')
        if use_cmd:
            # CMD /S /C needs an outer quote pair around the quoted script path.
            command = subprocess.list2cmdline([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c'])
            launcher = self.source / 'Install.cmd'
            if not launcher.exists():
                launcher = self.source / 'scripts/Install.cmd'
            command += ' "' + subprocess.list2cmdline([str(launcher)] + arguments) + '"'
            return subprocess.run(command, input=b'\r\n', capture_output=True, timeout=35)
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(self.source / 'scripts/install.ps1')] + arguments, capture_output=True, timeout=35)

    def shortcut_info(self, link):
        inspect_script = self.root / 'inspect.ps1'
        inspect_output = self.root / 'shortcut.json'
        inspect_script.write_text("param($Link,$Out,$Helper)\n. $Helper\n$s=Read-T3Shortcut $Link\n"
            "[IO.File]::WriteAllText($Out,(@{target=$s.TargetPath;arguments=$s.Arguments;directory=$s.WorkingDirectory}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))\n", encoding='utf-8')
        subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(inspect_script),
            str(link),str(inspect_output),str(self.source/'scripts/shortcut.ps1')],check=True,capture_output=True)
        return json.loads(inspect_output.read_text(encoding='utf-8'))

    def test_preview_discovers_custom_t3_and_makes_no_changes(self):
        before = self.db.read_bytes()
        result = self.call('-Preview')
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        # Decode with PowerShell instead of assuming the OEM console's encoding.
        self.assertIn(b'"preview"', result.stdout)
        self.assertFalse(self.install.exists())
        self.assertFalse((self.home / 'codex-autosync').exists())
        self.assertEqual(list(self.shortcuts.iterdir()), [])
        self.assertEqual(before, self.db.read_bytes())

    def test_install_and_reinstall_preserve_database_and_backup_shortcut(self):
        before = self.db.read_bytes()
        with patch.object(build_package, 'ROOT', self.source):
            archive_path = build_package.build()
        extracted = self.root / 'extracted'
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extracted)
        self.source = extracted / build_package.FOLDER
        self.assertTrue((self.source / 'Install.cmd').is_file())
        result = self.call(use_cmd=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        config = json.loads((self.install / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(config['t3_exe']), self.exe)
        self.assertEqual(Path(config['t3_home']), self.home)
        self.assertEqual(Path(config['codex_home']), self.codex)
        self.assertEqual(Path(config['node_exe']), Path(shutil.which('node.exe')))
        self.assertTrue((self.shortcuts / 'T3 Code (Auto Sync).lnk').is_file())
        self.assertEqual((self.install / 'licenses/T3-CODE-MIT.txt').read_bytes(),
                         (SOURCE / 'licenses/T3-CODE-MIT.txt').read_bytes())
        self.assertTrue((self.install / 'docs/RECOVERY.md').is_file())
        shortcut = self.shortcut_info(self.shortcuts / 'T3 Code (Auto Sync).lnk')
        self.assertEqual(Path(shortcut['target']),Path(sys.executable).with_name('pythonw.exe'))
        self.assertEqual(shortcut['arguments'],'"'+str(self.install / 'autosync.py')+'" --launch')
        self.assertEqual(before, self.db.read_bytes())
        result = self.call()
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertEqual(len(list((self.home/'codex-autosync'/'shortcut-backups').glob('*.lnk'))),1)
        self.assertEqual(before, self.db.read_bytes())

    def test_default_connects_existing_icons_and_preserves_custom_shortcuts(self):
        before = self.db.read_bytes()
        # Reproduce coarse Windows clock resolution: both originals have the
        # same filename and backup timestamp but must be preserved separately.
        installer = self.source / 'scripts/install.ps1'
        installer.write_text(installer.read_text(encoding='utf-8').replace(
            "Get-Date -Format 'yyyyMMdd-HHmmss-ffff'", "'20000101-000000-0000'"),encoding='utf-8')
        desktop = self.shortcuts / 'T3 Code.lnk'
        app_folder = self.exe.parent / 'T3 Code.lnk'
        custom = self.shortcuts / 'T3 custom.lnk'
        unrelated = self.shortcuts / 'Other app.lnk'
        seed_script = self.root / 'seed.ps1'
        seed_script.write_text(
            "param($Helper,$Target,$Desktop,$AppFolder,$Custom,$Other,$Python)\n. $Helper\n"
            "[T3Sync.Shortcuts]::Save($Desktop,$Target,'',[IO.Path]::GetDirectoryName($Target),$Target)\n"
            "[T3Sync.Shortcuts]::Save($AppFolder,$Target,'',[IO.Path]::GetDirectoryName($Target),$Target)\n"
            "[T3Sync.Shortcuts]::Save($Custom,$Target,'--profile example',[IO.Path]::GetDirectoryName($Target),$Target)\n"
            "[T3Sync.Shortcuts]::Save($Other,$Python,'',[IO.Path]::GetDirectoryName($Python),$Python)\n",
            encoding='utf-8')
        subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(seed_script),
            str(self.source/'scripts/shortcut.ps1'),str(self.exe),str(desktop),str(app_folder),
            str(custom),str(unrelated),sys.executable],check=True,capture_output=True)
        originals = {link:link.read_bytes() for link in (desktop,app_folder,custom,unrelated)}
        result = self.call(skip_existing=False)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        # The key is ASCII; Unicode paths are verified through native Shell links.
        self.assertIn(b'"desktopShortcut"',result.stdout)
        for link in (desktop,app_folder,self.shortcuts/'T3 Code (Auto Sync).lnk'):
            info = self.shortcut_info(link)
            self.assertEqual(Path(info['target']),Path(sys.executable).with_name('pythonw.exe'))
            self.assertEqual(info['arguments'],'"'+str(self.install/'autosync.py')+'" --launch')
            self.assertEqual(Path(info['directory']),self.install)
        self.assertEqual(custom.read_bytes(),originals[custom])
        self.assertEqual(unrelated.read_bytes(),originals[unrelated])
        backups = list((self.home/'codex-autosync'/'shortcut-backups').glob('*.lnk'))
        self.assertEqual(len(backups),2,[link.name for link in backups])
        self.assertCountEqual([link.read_bytes() for link in backups],
                              [originals[desktop],originals[app_folder]])
        self.assertEqual(before,self.db.read_bytes())

    def test_unsupported_t3_version_stops_before_install(self):
        with sqlite3.connect(str(self.db), factory=autosync.ClosingConnection) as db:
            db.execute('UPDATE effect_sql_migrations SET migration_id=82')
        before=self.db.read_bytes()
        result=self.call(use_cmd=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Unsupported T3 database',result.stderr)
        self.assertFalse(self.install.exists())
        self.assertEqual(list(self.shortcuts.iterdir()),[])
        self.assertEqual(before,self.db.read_bytes())


if __name__ == '__main__':
    unittest.main()
