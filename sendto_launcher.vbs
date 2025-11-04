' DBI Backend Qt - Silent Launcher (VBScript)
' This launches the Python application without any visible window

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get the directory where this script is located
strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Build command line with all arguments
strCommand = ""
strArgs = ""

' Get all arguments passed to this script
If WScript.Arguments.Count > 0 Then
    For i = 0 To WScript.Arguments.Count - 1
        strArgs = strArgs & " """ & WScript.Arguments(i) & """"
    Next
End If

' Try python3 first, then python
On Error Resume Next
objShell.Run "where python3", 0, True
If Err.Number = 0 Then
    strCommand = "pythonw3 """ & strScriptDir & "\main.py""" & strArgs
Else
    strCommand = "pythonw """ & strScriptDir & "\main.py""" & strArgs
End If
On Error GoTo 0

' Run the command invisibly (0 = hidden window, False = don't wait)
objShell.Run strCommand, 0, False
