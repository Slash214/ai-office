# Rebuild the x64 office launcher on Windows with the .NET Framework compiler.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$version = '1.0.3537.50'
$cache = Join-Path $root '.office-tools'
$runtime = Join-Path $PSScriptRoot 'webview2'
$null = New-Item -ItemType Directory -Force -Path $cache, $runtime
$sdk = Join-Path $cache "webview2.$version.nupkg"
if (!(Test-Path -LiteralPath $sdk)) {
    $uri = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$version/microsoft.web.webview2.$version.nupkg"
    Invoke-WebRequest -UseBasicParsing $uri -OutFile $sdk
}
if ((Get-FileHash -LiteralPath $sdk).Hash -ne '5EA526BBD728ADDA0DA4D31219267E96460494A427E4894C4E09D9F320F4B9AA') {
    throw 'The Microsoft WebView2 SDK package hash does not match the pinned release.'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($sdk)
try {
    foreach ($name in @('lib/net462/Microsoft.Web.WebView2.WinForms.dll','lib/net462/Microsoft.Web.WebView2.Core.dll','runtimes/win-x64/native/WebView2Loader.dll','LICENSE.txt')) {
        $entry = $archive.GetEntry($name)
        $destination = Join-Path $runtime $entry.Name
        if (Test-Path -LiteralPath $destination) {
            $stored = (Get-FileHash -LiteralPath $destination).Hash
            $stream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $expected = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') } finally { $sha.Dispose(); $stream.Dispose() }
            if ($stored -eq $expected) { continue }
        }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $true)
    }
} finally { $archive.Dispose() }
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
# Express the Unicode output name as code points for legacy Windows PowerShell.
$name = 'AI' + [char]0x5de5 + [char]0x4f5c + [char]0x5ba4 + '.exe'
$output = Join-Path $root $name
$sources = Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | ForEach-Object FullName
& $csc /nologo /optimize+ /platform:x64 /target:winexe /codepage:65001 "/out:$output" "/win32icon:$PSScriptRoot\office.ico" "/win32manifest:$PSScriptRoot\office.manifest" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/reference:$runtime\Microsoft.Web.WebView2.Core.dll" "/reference:$runtime\Microsoft.Web.WebView2.WinForms.dll" $sources
if ($LASTEXITCODE) { throw "C# compilation failed ($LASTEXITCODE)." }
Get-Item -LiteralPath $output
