; Inno Setup script. Build after PyInstaller: iscc installer.iss  ->  dist\CocoPDF-Setup-<version>.exe
#define AppName "Coco PDF"
#define AppVersion "0.6.0"
#define AppExe "CocoPDF.exe"

[Setup]
AppId={{6F1C3B52-8E0A-4C8F-9A5E-C0C0BDF00001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SARL Digital Rhapsody
AppCopyright=SARL Digital Rhapsody, 31700 Blagnac, France
DefaultDirName={autopf}\Coco PDF
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt); the dialog lets the user install for all users instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=CocoPDF-Setup-{#AppVersion}
SetupIconFile=assets\coco-pdf.ico
UninstallDisplayIcon={app}\{#AppExe}
; Two sizes: the second one is used on high-DPI screens.
WizardImageFile=assets\wizard-large.bmp,assets\wizard-large-2x.bmp
WizardSmallImageFile=assets\wizard-small.bmp
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Messages]
WelcomeLabel2=Cet assistant va installer [name/ver] sur votre ordinateur.%n%nÉditeur : SARL Digital Rhapsody, 31700 Blagnac, France%n%n« Coco, c'est ma maman, et à force de la voir galérer avec ses différents pdfs, j'ai décidé qu'il était temps que je lui crée un logiciel pour elle, pour son utilisation, puis aussi pour mon utilisation des pdfs... et finalement Coco PDF a vu le jour. Merci Maman :) »

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"
Name: "pdfassoc"; Description: "Proposer Coco PDF pour ouvrir les fichiers PDF"; GroupDescription: "Fichiers PDF :"

[Files]
Source: "dist\CocoPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Windows 10/11 never let an installer force the default app: this registers Coco PDF in "Open with",
; the user then picks it as default once (right click > Open with > Choose another app > Always).
Root: HKA; Subkey: "Software\Classes\CocoPDF.Document"; ValueType: string; ValueData: "Document PDF"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\CocoPDF.Document\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\CocoPDF.Document\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "CocoPDF.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: pdfassoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer Coco PDF"; Flags: nowait postinstall skipifsilent
