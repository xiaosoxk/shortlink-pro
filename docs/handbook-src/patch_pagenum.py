"""Post-process page numbering for WPS compatibility:
1. Remove empty <w:pgNumType/> emitted for the cover section.
2. Patch footer PAGE fields with explicit \\* ROMAN / \\* arabic switches,
   mapped per-section via footerReference -> rels.
"""
import re
import shutil
import sys
import zipfile

DOCX = sys.argv[1]
BAK = DOCX + ".bak"

with zipfile.ZipFile(DOCX, "r") as zin:
    entries = {n: zin.read(n) for n in zin.namelist()}

doc_xml = entries["word/document.xml"].decode("utf-8")
rels_xml = entries["word/_rels/document.xml.rels"].decode("utf-8")

rid_target = dict(re.findall(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels_xml))
# normalize: also handle attribute order variants
for m in re.finditer(r"<Relationship\b[^>]*/>", rels_xml):
    tag = m.group(0)
    rid = re.search(r'Id="([^"]+)"', tag)
    tgt = re.search(r'Target="([^"]+)"', tag)
    if rid and tgt:
        rid_target[rid.group(1)] = tgt.group(1)

sect_blocks = re.findall(r"<w:sectPr\b[\s\S]*?</w:sectPr>", doc_xml)
print(f"found {len(sect_blocks)} sectPr blocks")

patches = {}  # footer filename -> switch
for i, block in enumerate(sect_blocks):
    fmt_m = re.search(r'<w:pgNumType[^>]*w:fmt="(\w+)"', block)
    foot_m = re.search(r'<w:footerReference[^>]*w:type="default"[^>]*r:id="([^"]+)"', block) or \
             re.search(r'<w:footerReference[^>]*r:id="([^"]+)"[^>]*w:type="default"', block)
    if not foot_m:
        print(f"  section {i+1}: no default footer")
        continue
    target = rid_target.get(foot_m.group(1), "")
    fname = "word/" + target.lstrip("/") if not target.startswith("word/") else target
    fmt = fmt_m.group(1) if fmt_m else ""
    switch = "ROMAN" if "oman" in fmt.lower() or "ROMAN" in fmt else "arabic"
    patches[fname] = switch
    print(f"  section {i+1}: fmt={fmt or '(none)'} -> {fname} \\* {switch}")

changed = 0
for fname, switch in patches.items():
    if fname not in entries:
        print(f"  WARN: {fname} not in archive")
        continue
    xml = entries[fname].decode("utf-8")
    new_xml, n = re.subn(
        r"(<w:instrText[^>]*>)\s*PAGE\s*(</w:instrText>)",
        rf"\1 PAGE \\* {switch} \\* MERGEFORMAT \2",
        xml,
    )
    if n:
        entries[fname] = new_xml.encode("utf-8")
        changed += n
        print(f"  patched {fname}: {n} PAGE field(s) -> \\* {switch}")

# remove empty pgNumType (cover section)
doc_xml, removed = re.subn(r"<w:pgNumType/>", "", doc_xml)
print(f"removed {removed} empty pgNumType")
entries["word/document.xml"] = doc_xml.encode("utf-8")

shutil.copyfile(DOCX, BAK)
with zipfile.ZipFile(DOCX, "w", zipfile.ZIP_DEFLATED) as zout:
    for name, data in entries.items():
        zout.writestr(name, data)
print(f"done: {changed} footer fields patched, backup at {BAK}")
