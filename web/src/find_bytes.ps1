$path = 'D:\projects\tradefarm-f8\web\src\components\LlmModelPicker.tsx'
$bytes = [System.IO.File]::ReadAllBytes($path)
# Find positions of multi-byte sequences (em-dash = E2 80 94 in UTF-8)
$positions = @()
for ($i = 0; $i -lt $bytes.Count - 2; $i++) {
  if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) {
    $positions += $i
  }
}
Write-Output "Em-dash positions: $($positions.Count)"
foreach ($pos in $positions) {
  $line = (Get-Content $path -Encoding UTF8)[0..([Math]::Floor($pos / 100))]
  Write-Output "Position $pos (approx line)"
}
