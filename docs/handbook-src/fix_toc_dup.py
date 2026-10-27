"""Fix TOC duplicate first entry (generic):
The placeholder script merges the first entry into the field-start paragraph
AND sometimes inserts a standalone duplicate right after it. Delete the
standalone duplicate (same TOC1 style, same leading text) and inject the
cached page 'I' into the first entry's empty PAGEREF result.
"""
import re
import shutil
import sys
import zipfile

DOCX = sys.argv[1]

with zipfile.ZipFile(DOCX, "r") as zin:
    entries = {n: zin.read(n) for n in zin.namelist()}
xml = entries["word/document.xml"].decode("utf-8")

sdt_m = re.search(r"<w:sdt>[\s\S]*?</w:sdt>", xml)
assert sdt_m, "TOC sdt not found"
sdt = sdt_m.group(0)

paras = list(re.finditer(r"<w:p\b[\s\S]*?</w:p>", sdt))


def para_text(p_xml):
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p_xml)).strip()


field_start = next((p for p in paras if "instrText" in p.group(0) and "TOC" in p.group(0)), None)
assert field_start, "TOC field start paragraph not found"
first_text = re.sub(r"[IVX0-9]+$", "", para_text(field_start.group(0))).strip()
print("first entry text:", repr(first_text))

dup = None
for p in paras[paras.index(field_start) + 1:]:
    pxml = p.group(0)
    if 'w:val="TOC1"' not in pxml or "instrText" in pxml:
        continue
    t = para_text(pxml)
    if t.startswith(first_text) and len(t) <= len(first_text) + 4:
        dup = p
        break

if dup is None:
    print("no standalone duplicate found; nothing to delete")
else:
    sdt = sdt[:dup.start()] + sdt[dup.end():]
    print("deleted standalone duplicate entry:", repr(para_text(dup.group(0))[:40]))

sdt, n = re.subn(
    r'(<w:instrText[^>]*>\s*PAGEREF _Toc1 \\h\s*</w:instrText>\s*<w:fldChar w:fldCharType="separate"/>)(\s*<w:fldChar w:fldCharType="end"/>)',
    r'\1<w:r><w:t>I</w:t></w:r>\2',
    sdt,
)
print("PAGEREF _Toc1 cached result injected:", n)

xml = xml[:sdt_m.start()] + sdt + xml[sdt_m.end():]
entries["word/document.xml"] = xml.encode("utf-8")

shutil.copyfile(DOCX, DOCX + ".bak2")
with zipfile.ZipFile(DOCX, "w", zipfile.ZIP_DEFLATED) as zout:
    for name, data in entries.items():
        zout.writestr(name, data)
print("saved", DOCX)
