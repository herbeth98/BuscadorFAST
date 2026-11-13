@echo off
rem Gera BuscadorFAST.exe na pasta do programa (usa o compilador C# que vem com o Windows)
cd /d "%~dp0"
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:winexe /optimize+ ^
  /win32icon:icone.ico /r:System.Windows.Forms.dll /out:..\BuscadorFAST.exe BuscadorFAST.cs
