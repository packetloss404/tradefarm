$files = @(
  'D:\projects\tradefarm-f8\web\src\components\LlmModelPicker.tsx',
  'D:\projects\tradefarm-f8\web\src\components\AdminModal.tsx',
  'D:\projects\tradefarm-f8\web\src\api.ts'
)
foreach ($f in $files) {
  $bytes = [System.IO.File]::ReadAllBytes($f)
  $nonAscii = $bytes | Where-Object { $_ -gt 127 }
  if ($nonAscii) {
    Write-Output "$([System.IO.Path]::GetFileName($f)): $($nonAscii.Count) non-ASCII bytes"
  } else {
    Write-Output "$([System.IO.Path]::GetFileName($f)): pure ASCII"
  }
}
