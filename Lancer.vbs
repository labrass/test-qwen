Option Explicit
Dim shell, fso, folder, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(folder, "Lancer.ps1")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & script & """", 0, False
