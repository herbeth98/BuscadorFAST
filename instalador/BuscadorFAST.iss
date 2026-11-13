; Instalador do BuscadorFAST (Inno Setup 6). Para montar, rode instalador\montar.bat
; O instalador copia o programa e depois roda instalador\configurar.ps1, que baixa o Python,
; as bibliotecas de IA (com CUDA se houver placa NVIDIA) e os modelos.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "BuscadorFAST"
#define Raiz ".."

[Setup]
AppId={{8F3C2A71-5E4B-4C1D-9A2E-B7F04D6C1E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=BuscadorFAST
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Instalador do BuscadorFAST
DefaultDirName={localappdata}\Programs\BuscadorFAST
DisableProgramGroupPage=yes
DisableWelcomePage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Raiz}\dist
OutputBaseFilename=BuscadorFAST-Instalador-{#AppVersion}
SetupIconFile={#Raiz}\launcher\icone.ico
UninstallDisplayIcon={app}\launcher\icone.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=build\assistente-100.bmp,build\assistente-125.bmp,build\assistente-150.bmp,build\assistente-200.bmp,build\assistente-250.bmp
WizardSmallImageFile=build\icone-100.bmp,build\icone-125.bmp,build\icone-150.bmp,build\icone-200.bmp,build\icone-250.bmp
Compression=lzma2/max
SolidCompression=yes
; Python, PyTorch e os modelos de IA chegam depois, pela internet
ExtraDiskSpaceRequired=16106127360
CloseApplications=no
ShowLanguageDialog=no
SetupLogging=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
WelcomeLabel2=Isto vai instalar o [name/ver] neste computador.%n%nO BuscadorFAST encontra fotos e vídeos em todos os seus discos pelo conteúdo: o que aparece na imagem, as pessoas, o texto escrito, o que é falado e os sons. Tudo roda no próprio computador.%n%nNo fim, o instalador baixa o Python e a inteligência artificial (alguns gigabytes). Deixe o computador ligado e conectado à internet.
FinishedLabel=O BuscadorFAST está instalado.%n%nPara começar, abra o programa, clique em Ferramentas → Indexar discos e escolha os discos com suas fotos e vídeos.

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"
Name: "startmenu"; Description: "Criar um atalho no Menu Iniciar"
Name: "modelos"; Description: "Baixar agora todos os modelos de IA (cerca de 12 GB). Sem isso, cada um é baixado na primeira vez em que for usado."; Flags: unchecked

[Files]
Source: "{#Raiz}\buscador\*.py"; DestDir: "{app}\buscador"; Flags: ignoreversion
Source: "{#Raiz}\web\*"; DestDir: "{app}\web"; Flags: ignoreversion recursesubdirs
Source: "{#Raiz}\launcher\*"; DestDir: "{app}\launcher"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion
Source: "{#Raiz}\logo\*"; DestDir: "{app}\logo"; Flags: ignoreversion
Source: "{#Raiz}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Raiz}\requirements-lock.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Raiz}\LEIAME.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Raiz}\BuscadorFAST.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "configurar.ps1"; DestDir: "{app}\instalador"; Flags: ignoreversion
Source: "desinstalar.ps1"; DestDir: "{app}\instalador"; Flags: ignoreversion
Source: "build\BuscadorFAST.exe"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\models\hf"

[Icons]
Name: "{autoprograms}\BuscadorFAST"; Filename: "{app}\BuscadorFAST.exe"; WorkingDir: "{app}"; IconFilename: "{app}\launcher\icone.ico"; Tasks: startmenu
Name: "{autodesktop}\BuscadorFAST"; Filename: "{app}\BuscadorFAST.exe"; WorkingDir: "{app}"; IconFilename: "{app}\launcher\icone.ico"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\instalador\configurar.ps1"" -Pasta ""{app}"" -Modelos{code:SemPausa}"; StatusMsg: "Preparando o Python e a IA. O andamento aparece na janela preta; pode levar vários minutos..."; Tasks: modelos; Flags: waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\instalador\configurar.ps1"" -Pasta ""{app}""{code:SemPausa}"; StatusMsg: "Preparando o Python e a IA. O andamento aparece na janela preta; pode levar vários minutos..."; Tasks: not modelos; Flags: waituntilterminated
Filename: "{app}\BuscadorFAST.exe"; Description: "Abrir o BuscadorFAST agora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\instalador\desinstalar.ps1"" -Pasta ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "FecharPrograma"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\buscador\__pycache__"

[Code]
// instalação silenciosa (/VERYSILENT): o configurar.ps1 não espera Enter se algo falhar
function SemPausa(Param: String): String;
begin
  if WizardSilent then Result := ' -SemPausa' else Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dados := ExpandConstant('{app}\data');
    if DirExists(Dados) then
      if SuppressibleMsgBox('Apagar também o catálogo do BuscadorFAST?' + #13#10#13#10 +
        'São as palavras-chave, os nomes das pessoas, as coleções e as miniaturas. Suas fotos e vídeos não são apagados.' + #13#10#13#10 +
        'Escolha "Não" para guardar o catálogo e usá-lo se instalar de novo.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
        DelTree(Dados, True, True, True);
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
