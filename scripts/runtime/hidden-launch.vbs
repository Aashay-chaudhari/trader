Option Explicit
Dim fs, shell, folder, script, mode, command, result
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
mode = "watchdog"
If WScript.Arguments.Count > 0 Then mode = WScript.Arguments(0)
Select Case mode
  Case "status": script = "inspect-runtime.ps1"
  Case "publish": script = "git-push.ps1"
  Case "host": script = "wsl-host.ps1"
  Case "watchdog": script = "watchdog.ps1"
  Case "install": script = "install-task.ps1"
  Case Else: WScript.Quit 2
End Select
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & folder & "\" & script & """"
' wscript is a GUI host; window style 0 also hides PowerShell and its child launcher.
result = shell.Run(command, 0, True)
WScript.Quit result
