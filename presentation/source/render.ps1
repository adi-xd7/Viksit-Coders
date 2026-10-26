# Exports the deck to PDF and to one PNG per slide using installed PowerPoint (real fonts).
# Usage: powershell -ExecutionPolicy Bypass -File render.ps1 <deck.pptx> <pdf_out> [png_dir]
param([string]$Deck, [string]$Pdf, [string]$PngDir = "")
$ErrorActionPreference = "Stop"
$deckPath = (Resolve-Path $Deck).Path
$pp = New-Object -ComObject PowerPoint.Application
try {
  $p = $pp.Presentations.Open($deckPath, $true, $false, $false)  # read-only, no window
  $p.SaveAs([System.IO.Path]::GetFullPath($Pdf), 32)              # 32 = ppSaveAsPDF
  if ($PngDir -ne "") {
    New-Item -ItemType Directory -Force -Path $PngDir | Out-Null
    $dir = (Resolve-Path $PngDir).Path
    foreach ($s in $p.Slides) { $s.Export((Join-Path $dir ("slide-{0:D2}.png" -f $s.SlideIndex)), "PNG", 1600, 900) }
  }
  $p.Close()
} finally {
  $pp.Quit()
}
