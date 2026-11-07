Option Explicit
Dim fs, shell, folder, script, mode, command, result, revision, pattern
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
If mode = "publish" Then
  If WScript.Arguments.Count <> 2 Then WScript.Quit 2
  revision = WScript.Arguments(1)
  If Len(revision) <> 40 Then WScript.Quit 2
  Set pattern = New RegExp
  pattern.Pattern = "^[0-9a-f]{40}$"
  If Not pattern.Test(revision) Then WScript.Quit 2
  command = command & " -Revision " & revision
End If
' wscript is a GUI host; window style 0 also hides PowerShell and its child launcher.
result = shell.Run(command, 0, True)
WScript.Quit result
