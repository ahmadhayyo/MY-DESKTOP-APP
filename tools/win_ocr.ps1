# win_ocr.ps1 — Native Windows 11 OCR via Windows.Media.Ocr (no Tesseract needed)
# Usage:
#   Text mode (default):  powershell -File win_ocr.ps1 -ImagePath "C:\img.png"
#   Words mode (JSON):    powershell -File win_ocr.ps1 -ImagePath "C:\img.png" -Mode words
# Text mode outputs recognized text line-by-line (UTF-8).
# Words mode outputs one JSON object per line: {"t":"word","x":..,"y":..,"w":..,"h":..}
param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,
    [Parameter(Mandatory = $false)]
    [ValidateSet("text", "words")]
    [string]$Mode = "text"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    # Helper to await WinRT async operations
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]

    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }

    # Load WinRT types
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.FileAccessMode, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

    # Open the image file
    $storageFile = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
    $stream = Await ($storageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    # Try Arabic+English: build engine from user profile languages (covers both installed langs)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        # Fallback to English explicitly
        [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
        $lang = New-Object Windows.Globalization.Language "en-US"
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    }

    if ($null -eq $engine) {
        Write-Output "__OCR_ENGINE_NULL__"
        exit 0
    }

    $ocrResult = Await ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])

    if ($Mode -eq "words") {
        # Output word-level bounding boxes as JSON lines
        foreach ($line in $ocrResult.Lines) {
            foreach ($word in $line.Words) {
                $r = $word.BoundingRect
                $txt = $word.Text -replace '\\', '\\\\' -replace '"', '\"'
                $json = '{{"t":"{0}","x":{1},"y":{2},"w":{3},"h":{4}}}' -f `
                    $txt, [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height
                [Console]::Out.WriteLine($json)
            }
        }
    }
    else {
        # Output line by line to preserve layout
        foreach ($line in $ocrResult.Lines) {
            [Console]::Out.WriteLine($line.Text)
        }
    }
}
catch {
    Write-Output "__OCR_ERROR__: $($_.Exception.Message)"
    exit 1
}
