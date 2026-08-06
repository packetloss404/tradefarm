$path = 'D:\projects\tradefarm-f8\web\src\components\LlmModelPicker.tsx'
$content = Get-Content $path -Encoding UTF8
for ($i = 0; $i -lt $content.Count; $i++) {
  $line = $content[$i]
  if ($line -match '[\u2014\u2192\u2713]') {
    Write-Output "Line $($i+1): $line"
  }
}
