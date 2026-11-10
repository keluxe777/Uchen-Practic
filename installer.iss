; Установщик «Расшифровщика аудио» (Inno Setup 6). Собирается из build.bat:
;   ISCC.exe /DAppVersion=1.4 installer.iss
; Берёт готовую папку dist\Расшифровщик аудио (exe + библиотеки + модель base)
; и делает один файл dist\Расшифровщик аудио <версия> - установка.exe.

#define AppName "Расшифровщик аудио"
#define AppExe "Расшифровщик аудио.exe"
#ifndef AppVersion
  #define AppVersion "1.4"
#endif

[Setup]
; Постоянный номер программы: по нему новая версия ставится поверх старой
AppId={{42177B2C-18B2-45B3-B48A-0965DDF9CC18}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Калинин А. Е., Ганичев А. Л. (ИСП-225П)
AppPublisherURL=https://github.com/keluxe777/Uchen-Practic
VersionInfoVersion={#AppVersion}
; Выбор: «только для меня» (без прав администратора) или «для всех пользователей»
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Страница выбора папки установки и папки в меню «Пуск»
DefaultDirName={autopf}\{#AppName}
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=no
; Флажок «Не создавать папку в меню «Пуск»»
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename={#AppName} {#AppVersion} - установка
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Если программа открыта, установщик предложит её закрыть
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Скачанные модели и история, которые программа создала в своей папке
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\data"
