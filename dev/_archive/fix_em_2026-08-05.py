
path = 'D:/projects/tradefarm-f8/web/src/components/LlmModelPicker.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace em-dash with ASCII " -- " (note: no spaces added; preserve existing spacing)
# em-dash character: U+2014
content = content.replace('\u2014', '--')
# Right arrow: U+2192
content = content.replace('\u2192', '->')
# Check mark: U+2713
content = content.replace('\u2713', 'OK')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
with open(path, 'rb') as f:
    raw = f.read()
non_ascii = [b for b in raw if b > 127]
print(f'Non-ASCII bytes remaining: {len(non_ascii)}')
