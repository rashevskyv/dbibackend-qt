# Installs the inbox WinUSB driver for the Switch (USB\VID_057E&PID_3000).
# Same approach as Zadig/libwdi, using only Windows built-ins: generate an INF,
# catalog it, sign the catalog with a fresh self-signed certificate that is
# trusted on this machine only (its private key is deleted right after signing),
# then stage and install the package with pnputil. Must run elevated.
param(
    [string]$HardwareId = 'USB\VID_057E&PID_3000',
    [string]$DeviceName = 'Nintendo Switch (DBI)',
    [string]$LogPath = ''
)
$ErrorActionPreference = 'Stop'

# The caller cannot read an elevated process's output, so results go to a log file.
function Write-Log([string]$text) {
    if ($LogPath) { $text | Out-File -FilePath $LogPath -Append -Encoding utf8 }
}

$dir = Join-Path $env:TEMP ('dbi-winusb-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $dir | Out-Null
    $inf = Join-Path $dir 'dbi_winusb.inf'
    $cat = Join-Path $dir 'dbi_winusb.cat'
    $date = [datetime]::Now.ToString('MM/dd/yyyy', [Globalization.CultureInfo]::InvariantCulture)

    @"
[Version]
Signature   = "`$Windows NT`$"
Class       = USBDevice
ClassGuid   = {88bae032-5a81-49f0-bc3d-a4ff138216d6}
Provider    = %VendorName%
CatalogFile = dbi_winusb.cat
DriverVer   = $date,6.1.7600.16385

[Manufacturer]
%VendorName% = Switch,NTamd64,NTx86,NTarm64

[Switch.NTamd64]
%DeviceName% = USB_Install, $HardwareId

[Switch.NTx86]
%DeviceName% = USB_Install, $HardwareId

[Switch.NTarm64]
%DeviceName% = USB_Install, $HardwareId

[USB_Install]
Include = winusb.inf
Needs   = WINUSB.NT

[USB_Install.Services]
Include = winusb.inf
Needs   = WINUSB.NT.Services

[USB_Install.HW]
AddReg = Dev_AddReg

[Dev_AddReg]
HKR,,DeviceInterfaceGUIDs,0x10000,"{4D36E2B4-6F1C-4E52-9C7B-0D2A9E8B5A01}"

[Strings]
VendorName = "DBI Backend Qt"
DeviceName = "$DeviceName"
"@ | Set-Content -Path $inf -Encoding ASCII

    New-FileCatalog -Path $inf -CatalogFilePath $cat -CatalogVersion 2.0 | Out-Null

    $cert = New-SelfSignedCertificate -Type CodeSigningCert `
        -Subject 'CN=DBI Backend Qt USB driver (this PC only)' `
        -CertStoreLocation Cert:\LocalMachine\My -NotAfter (Get-Date).AddYears(30)
    try {
        $cer = Join-Path $dir 'signer.cer'
        Export-Certificate -Cert $cert -FilePath $cer | Out-Null
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
        $sig = Set-AuthenticodeSignature -FilePath $cat -Certificate $cert -HashAlgorithm SHA256
        if ($sig.Status -ne 'Valid') { throw "Catalog signing failed: $($sig.StatusMessage)" }
    } finally {
        # Nobody can sign anything else with this certificate once the key is gone.
        Remove-Item -Path $cert.PSPath -DeleteKey -ErrorAction SilentlyContinue
    }

    $out = & pnputil.exe /add-driver $inf /install 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Log $out
    # 0 = installed, 3010 = reboot needed, 259 = staged but no matching device plugged in yet
    if ($code -in 0, 3010, 259) { exit 0 }
    exit $code
} catch {
    Write-Log "$_"
    exit 1
} finally {
    Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
}
