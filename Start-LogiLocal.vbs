Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If fs.FileExists(folder & "\desktop\dist\index.html") And fs.FileExists(folder & "\desktop\node_modules\electron\dist\electron.exe") Then
  shell.Run Chr(34) & folder & "\desktop\node_modules\electron\dist\electron.exe" & Chr(34) & " " & Chr(34) & folder & "\desktop" & Chr(34), 1, False
Else
  shell.Run Chr(34) & folder & "\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & folder & "\launch.py" & Chr(34), 0, False
End If
