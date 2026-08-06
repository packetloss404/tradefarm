$bytes = [System.IO.File]::ReadAllBytes('D:\projects\tradefarm-f8\web\src\components\LlmModelPicker.tsx')
$nonAscii = $bytes | Where-Object { $_ -gt 127 }
if ($nonAscii) {
  Write-Output "Non-ASCII bytes: $($nonAscii.Count) found"
  $nonAscii | Select-Object -First 10 | ForEach-Object { Write-Output "  byte=$_" }
} else {
  Write-Output "Pure ASCII"
}
