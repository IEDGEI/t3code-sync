# Unicode Shell links for both English and non-English Windows installations.
# IShellLinkW + IPersistFile avoid WScript.Shell's locale-dependent file paths.
if (-not ('T3Sync.Shortcuts' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
namespace T3Sync {
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count, IntPtr data, uint flags);
        void GetIDList(out IntPtr value);
        void SetIDList(IntPtr value);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short value);
        void SetHotkey(short value);
        void GetShowCmd(out int value);
        void SetShowCmd(int value);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
        void Resolve(IntPtr window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
    }
    public sealed class ShortcutInfo {
        public string TargetPath;
        public string Arguments;
        public string WorkingDirectory;
        public string IconLocation;
    }
    public static class Shortcuts {
        private static object Create() {
            return Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
        }
        public static void Save(string path, string target, string arguments, string directory, string icon) {
            object instance = Create();
            try {
                IShellLinkW link = (IShellLinkW)instance;
                link.SetPath(target);
                link.SetArguments(arguments);
                link.SetWorkingDirectory(directory);
                link.SetIconLocation(icon, 0);
                link.SetDescription("Update imported Codex chats, then start T3 Code.");
                ((IPersistFile)instance).Save(path, true);
            } finally { Marshal.FinalReleaseComObject(instance); }
        }
        public static ShortcutInfo Read(string path) {
            object instance = Create();
            try {
                ((IPersistFile)instance).Load(path, 0);
                IShellLinkW link = (IShellLinkW)instance;
                StringBuilder target = new StringBuilder(32768);
                StringBuilder arguments = new StringBuilder(32768);
                StringBuilder directory = new StringBuilder(32768);
                StringBuilder icon = new StringBuilder(32768);
                int index;
                link.GetPath(target, target.Capacity, IntPtr.Zero, 0);
                link.GetArguments(arguments, arguments.Capacity);
                link.GetWorkingDirectory(directory, directory.Capacity);
                link.GetIconLocation(icon, icon.Capacity, out index);
                return new ShortcutInfo { TargetPath = target.ToString(), Arguments = arguments.ToString(),
                    WorkingDirectory = directory.ToString(), IconLocation = icon.ToString() + "," + index };
            } finally { Marshal.FinalReleaseComObject(instance); }
        }
    }
}
'@
}

function Read-T3Shortcut([string]$Path) {
    try { return [T3Sync.Shortcuts]::Read($Path) } catch { return $null }
}
