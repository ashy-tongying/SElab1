Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")

Function Exists(cmd)
  Exists = (sh.Run("cmd /c where " & cmd & " >nul 2>&1", 0, True) = 0)
End Function

If Exists("pythonw") Then
  launch = "pythonw main.py"
ElseIf Exists("pyw") Then
  launch = "pyw -3 main.py"
ElseIf Exists("python") Then
  launch = "python main.py"
ElseIf Exists("py") Then
  launch = "py -3 main.py"
Else
  MsgBox "Python was not found. Install Python 3.11 and add it to PATH.", 16, "Huodonghui"
  WScript.Quit 1
End If
sh.Run "cmd /c cd /d """ & folder & """ && start """" " & launch, 0, False
