$path = 'D:\projects\tradefarm-f8\web\src\components\LlmModelPicker.tsx'
$content = Get-Content $path -Encoding UTF8
$bytePos = 0
$lines = @()
for ($i = 0; $i -lt $content.Count; $i++) {
  $lines += [PSCustomObject]@{ Line = $i + 1; Text = $content[$i]; Start = $bytePos }
  $bytePos += [System.Text.Encoding]::UTF8.GetByteCount($content[$i]) + 2  # +2 for CRLF
}
foreach ($em in @(10, 604, 4713, 13222)) {
  $line = $lines | Where-Object { $_.Start -le $em -and $em -lt ($_.Start + [System.Text.Encoding]::UTF8.GetByteCount($_.Text) + 2) } | Select-Object -First 1
  if ($line) {
    Write-Output "Em-dash at byte $em -- Line $($line.Line): $($line.Text)"
  }
}
