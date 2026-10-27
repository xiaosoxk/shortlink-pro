/* Python interview handbook generator: markdown subset -> docx (skill-compliant) */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  PageBreak, Header, Footer, PageNumber, NumberFormat, SectionType,
  AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType,
  TableLayoutType, LevelFormat, TableOfContents,
} = require("docx");
const fs = require("fs");
const path = require("path");

/* ---------------- palette (DM-1 Deep Cyan, tech) ---------------- */
const PAL = {
  bg: "162235",
  cover: { titleColor: "FFFFFF", subtitleColor: "B0B8C0", metaColor: "90989F", footerColor: "687078" },
  accent: "37DCF2",
  primary: "0A1628",
  table: { headerBg: "1B6B7A", headerText: "FFFFFF", accentLine: "1B6B7A", innerLine: "C8DDE2", surface: "EDF3F5" },
  codeBg: "EDF3F5",
  codeText: "24323F",
  calloutText: "3A3A3A",
};

const FONT_BODY = { ascii: "Times New Roman", eastAsia: "SimSun" };
const FONT_HEAD = { ascii: "Times New Roman", eastAsia: "SimHei" };
const FONT_CODE = { ascii: "Courier New", eastAsia: "Microsoft YaHei" };

const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };

/* ---------------- cover helpers (from design-system.md) ---------------- */
function splitTitleLines(title, charsPerLine) {
  if (title.length <= charsPerLine) return [title];
  const breakAfter = new Set([..."\uff0c\u3002\u3001\uff1b\uff1a\uff01\uff1f", ..."\u7684\u4e0e\u548c\u53ca\u4e4b\u5728\u4e8e\u4e3a", ..."-_\u2014\u2013\u00b7/", ..." \t"]);
  const lines = [];
  let remaining = title;
  while (remaining.length > charsPerLine) {
    let breakAt = -1;
    for (let i = charsPerLine; i >= Math.floor(charsPerLine * 0.6); i--) {
      if (i < remaining.length && breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
    }
    if (breakAt === -1) {
      const limit = Math.min(remaining.length, Math.ceil(charsPerLine * 1.3));
      for (let i = charsPerLine + 1; i < limit; i++) {
        if (breakAfter.has(remaining[i - 1])) { breakAt = i; break; }
      }
    }
    if (breakAt === -1) {
      breakAt = charsPerLine;
      const prevChar = remaining[breakAt - 1], nextChar = remaining[breakAt];
      if (prevChar && nextChar && !breakAfter.has(prevChar) && !breakAfter.has(nextChar) &&
          /[\u4e00-\u9fff]/.test(prevChar) && /[\u4e00-\u9fff]/.test(nextChar)) breakAt -= 1;
    }
    lines.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) lines.push(remaining);
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop();
    lines[lines.length - 1] += last;
  }
  return lines;
}

function calcTitleLayout(title, maxWidthTwips, preferredPt = 40, minPt = 24) {
  const charWidth = (pt) => pt * 20;
  const charsPerLine = (pt) => Math.floor(maxWidthTwips / charWidth(pt));
  let titlePt = preferredPt, lines;
  while (titlePt >= minPt) {
    const cpl = charsPerLine(titlePt);
    if (cpl < 2) { titlePt -= 2; continue; }
    lines = splitTitleLines(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) {
    lines = splitTitleLines(title, charsPerLine(minPt));
    titlePt = minPt;
  }
  return { titlePt, titleLines: lines };
}

function calcCoverSpacing(params) {
  const { titleLineCount = 1, titlePt = 36, hasSubtitle = false, hasEnglishLabel = false,
          metaLineCount = 0, fixedHeight = 800, pageHeight = 16838, marginTop = 0, marginBottom = 0 } = params;
  const SAFETY = 1200;
  const usableHeight = pageHeight - marginTop - marginBottom - SAFETY;
  const titleHeight = titleLineCount * (titlePt * 23 + 200);
  const subtitleHeight = hasSubtitle ? (12 * 23 + 600) : 0;
  const englishLabelHeight = hasEnglishLabel ? (9 * 23 + 600) : 0;
  const metaHeight = metaLineCount * (10 * 23 + 100);
  const implicitParaHeight = 3 * 300;
  const contentHeight = titleHeight + subtitleHeight + englishLabelHeight + metaHeight + fixedHeight + implicitParaHeight;
  const remainingSpace = usableHeight - contentHeight;
  const safeRemaining = Math.max(remainingSpace, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(safeRemaining * 0.45);
  const rawBottom = Math.floor(safeRemaining * 0.45);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  const midSpacing = Math.max(safeRemaining - topSpacing - bottomSpacing, 0);
  return { topSpacing, midSpacing, bottomSpacing };
}

function buildCoverR1(config) {
  const P = config.palette;
  const padL = 1200, padR = 800;
  const availableWidth = 11906 - padL - padR - 300;
  const { titlePt, titleLines } = calcTitleLayout(config.title, availableWidth, 40, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length, fixedHeight: 400,
  });
  const accentLeft = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];
  children.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));
  if (config.englishLabel) {
    children.push(new Paragraph({
      indent: { left: padL, right: padR }, spacing: { after: 500 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
      children: [new TextRun({ text: config.englishLabel.split("").join("  "), size: 18, color: P.accent,
        font: { ascii: "Calibri", eastAsia: "SimHei" }, characterSpacing: 40 })],
    }));
  }
  for (let i = 0; i < titleLines.length; i++) {
    children.push(new Paragraph({
      indent: { left: padL },
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [new TextRun({ text: titleLines[i], size: titleSize, bold: true,
        color: P.cover.titleColor, font: { eastAsia: "SimHei", ascii: "Arial" } })],
    }));
  }
  if (config.subtitle) {
    children.push(new Paragraph({
      indent: { left: padL }, spacing: { after: 800 },
      children: [new TextRun({ text: config.subtitle, size: 24, color: P.cover.subtitleColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }
  for (const line of (config.metaLines || [])) {
    children.push(new Paragraph({
      indent: { left: padL + 200 }, spacing: { after: 80 },
      border: { left: accentLeft },
      children: [new TextRun({ text: line, size: 24, color: P.cover.metaColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }
  children.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));
  children.push(new Paragraph({
    indent: { left: padL, right: padR },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerLeft || "", size: 16, color: P.cover.footerColor, font: { ascii: "Arial" } }),
      new TextRun({ text: "                                        ", font: { ascii: "Arial" }, size: 16, color: P.cover.footerColor }),
      new TextRun({ text: config.footerRight || "", size: 16, color: P.cover.footerColor, font: { ascii: "Arial" } }),
    ],
  }));
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg }, borders: noBorders,
        children,
      })],
    })],
  })];
}

/* ---------------- inline markdown -> runs ---------------- */
function inlineRuns(text, base) {
  const runs = [];
  const tokens = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  for (const tk of tokens) {
    if (!tk) continue;
    if (tk.startsWith("**") && tk.endsWith("**") && tk.length > 4) {
      runs.push(new TextRun({ ...base, text: tk.slice(2, -2), bold: true }));
    } else if (tk.startsWith("`") && tk.endsWith("`") && tk.length > 2) {
      runs.push(new TextRun({ text: tk.slice(1, -1), size: 22, color: PAL.table.headerBg, font: FONT_CODE }));
    } else {
      runs.push(new TextRun({ ...base, text: tk }));
    }
  }
  return runs;
}

const BODY_RUN = { size: 24, color: "000000", font: FONT_BODY };

/* ---------------- markdown block parser ---------------- */
function parseMarkdown(md) {
  const lines = md.split(/\r?\n/);
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }
    if (line.startsWith("```")) {
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) { codeLines.push(lines[i]); i++; }
      i++; // closing fence
      blocks.push({ type: "code", lines: codeLines });
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const tableLines = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { tableLines.push(lines[i].trim()); i++; }
      const splitRow = (l) => l.slice(1, -1).replace(/\\\|/g, "\u0001").split("|").map((c) => c.trim().replace(/\u0001/g, "|"));
      const cells = tableLines.map(splitRow);
      const header = cells[0];
      let rows = cells.slice(1);
      if (rows.length && rows[0].every((c) => /^:?-{2,}:?$/.test(c))) rows = rows.slice(1);
      blocks.push({ type: "table", header, rows });
      continue;
    }
    if (line.startsWith(">")) {
      blocks.push({ type: "callout", text: line.replace(/^>\s?/, "") });
      i++; continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { blocks.push({ type: "heading", level: h[1].length, text: h[2] }); i++; continue; }
    if (/^\s*-\s+/.test(line)) {
      const indent = line.match(/^(\s*)/)[1].length;
      blocks.push({ type: "bullet", level: indent >= 2 ? 1 : 0, text: line.replace(/^\s*-\s+/, "") });
      i++; continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      blocks.push({ type: "ordered", text: line.replace(/^\d+\.\s+/, "") });
      i++; continue;
    }
    blocks.push({ type: "para", text: line });
    i++;
  }
  return blocks;
}

/* ---------------- block builders ---------------- */
let firstH1Seen = false;

function buildHeading(level, text) {
  const cfg = {
    1: { h: HeadingLevel.HEADING_1, size: 32, before: 400, after: 200, center: true },
    2: { h: HeadingLevel.HEADING_2, size: 30, before: 320, after: 140, center: false },
    3: { h: HeadingLevel.HEADING_3, size: 28, before: 260, after: 110, center: false },
    4: { h: HeadingLevel.HEADING_4, size: 26, before: 220, after: 90, center: false },
  }[level];
  const pbb = level === 1 && firstH1Seen;
  if (level === 1) firstH1Seen = true;
  return new Paragraph({
    heading: cfg.h,
    alignment: cfg.center ? AlignmentType.CENTER : AlignmentType.LEFT,
    pageBreakBefore: pbb,
    spacing: { before: cfg.before, after: cfg.after, line: 312 },
    children: [new TextRun({ text, bold: true, size: cfg.size, color: PAL.primary, font: FONT_HEAD })],
  });
}

function buildPara(text) {
  let pb = false;
  if (text.endsWith("[[PB]]")) { text = text.slice(0, -6).trim(); pb = true; }
  const children = inlineRuns(text, BODY_RUN);
  if (pb) children.push(new PageBreak());
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: 480 },
    spacing: { line: 312, after: 60 },
    children,
  });
}

function buildBullet(text, level) {
  return new Paragraph({
    bullet: { level },
    alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 312, after: 40 },
    children: inlineRuns(text, BODY_RUN),
  });
}

function buildOrdered(text, ref) {
  return new Paragraph({
    numbering: { reference: ref, level: 0 },
    alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 312, after: 40 },
    children: inlineRuns(text, BODY_RUN),
  });
}

function buildCode(lines) {
  return lines.map((ln, idx) => new Paragraph({
    spacing: { line: 312, before: idx === 0 ? 120 : 0, after: idx === lines.length - 1 ? 120 : 0 },
    shading: { type: ShadingType.CLEAR, fill: PAL.codeBg },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: PAL.table.accentLine, space: 8 } },
    indent: { left: 240, right: 120 },
    children: [new TextRun({ text: ln.length ? ln : " ", size: 18, color: PAL.codeText, font: FONT_CODE })],
  }));
}

function buildCallout(text) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { left: 240 },
    spacing: { line: 312, before: 60, after: 60 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: PAL.table.accentLine, space: 10 } },
    children: inlineRuns(text, { size: 22, color: PAL.calloutText, font: FONT_BODY }),
  });
}

function buildTable(header, rows) {
  const n = header.length;
  const widths = n === 2 ? [30, 70] : Array(n).fill(Math.floor(100 / n));
  const cellMargins = { top: 60, bottom: 60, left: 120, right: 120 };
  const headerRow = new TableRow({
    tableHeader: true,
    cantSplit: true,
    children: header.map((text, idx) => new TableCell({
      shading: { type: ShadingType.CLEAR, fill: PAL.table.headerBg },
      margins: cellMargins,
      width: { size: widths[idx], type: WidthType.PERCENTAGE },
      children: [new Paragraph({
        spacing: { line: 312 },
        children: [new TextRun({ text, bold: true, size: 21, color: PAL.table.headerText, font: FONT_HEAD })],
      })],
    })),
  });
  const dataRows = rows.map((row) => new TableRow({
    cantSplit: true,
    children: header.map((_, idx) => new TableCell({
      margins: cellMargins,
      width: { size: widths[idx], type: WidthType.PERCENTAGE },
      children: [new Paragraph({
        spacing: { line: 312 },
        children: inlineRuns(row[idx] || "", { size: 21, color: "000000", font: FONT_BODY }),
      })],
    })),
  }));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: PAL.table.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: PAL.table.accentLine },
      left: NB, right: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: PAL.table.innerLine },
      insideVertical: NB,
    },
    rows: [headerRow, ...dataRows],
  });
}

function renderBlocks(blocks) {
  const out = [];
  let olIndex = 0;
  const numberingConfigs = [];
  let prevOrdered = false;
  for (const b of blocks) {
    if (b.type === "heading") out.push(buildHeading(b.level, b.text));
    else if (b.type === "para") out.push(buildPara(b.text));
    else if (b.type === "bullet") out.push(buildBullet(b.text, b.level));
    else if (b.type === "ordered") {
      const ref = "ol-" + (++olIndex);
      numberingConfigs.push(ref);
      out.push(buildOrdered(b.text, ref));
    } else if (b.type === "code") out.push(...buildCode(b.lines));
    else if (b.type === "callout") out.push(buildCallout(b.text));
    else if (b.type === "table") { out.push(buildTable(b.header, b.rows)); out.push(new Paragraph({ spacing: { line: 312, after: 60 }, children: [] })); }
    prevOrdered = b.type === "ordered";
  }
  return { elements: out, numberingConfigs };
}

/* ---------------- assemble document ---------------- */
/* 用法: node generate.js [spec.json]
   spec = { parts: [...], out: "...", title: "...", subtitle: "...",
            englishLabel, metaLines: [...], footerLeft, footerRight }
   不传 spec 时保持原默认行为 */
const CONTENT_DIR = path.join(__dirname, "content");
const SPEC_FILE = process.argv[2] || null;
const SPEC = SPEC_FILE ? JSON.parse(fs.readFileSync(SPEC_FILE, "utf8")) : null;
const partFiles = SPEC
  ? SPEC.parts
  : [
  "00-\u524d\u8a00.md",
  "01-\u8bed\u8a00\u6838\u5fc3.md",
  "02-\u5e76\u53d1\u4e0e\u5f02\u6b65.md",
  "03-Web\u5f00\u53d1.md",
  "04-\u6570\u636e\u5e93\u4e0e\u7f13\u5b58.md",
  "05-\u6d4b\u8bd5\u4e0e\u8d28\u91cf.md",
  "06-\u5de5\u7a0b\u5316\u4e0e\u6027\u80fd.md",
  "07-\u6570\u636e\u5904\u7406\u4e0e\u5e38\u7528\u5e93.md",
  "08-\u7cfb\u7edf\u8bbe\u8ba1\u4e0e\u901f\u7b54.md",
];

const allNumbering = [];
const bodyChildren = [];
let frontChildren = [];

for (const f of partFiles) {
  const md = fs.readFileSync(path.join(CONTENT_DIR, f), "utf8");
  const blocks = parseMarkdown(md);
  const { elements, numberingConfigs } = renderBlocks(blocks);
  allNumbering.push(...numberingConfigs);
  if (f.includes("00-")) frontChildren = elements;
  else bodyChildren.push(...elements);
}

/* front matter: preface (ends with [[PB]]) + TOC */
const tocTitle = new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 480, after: 360, line: 312 },
  children: [new TextRun({ text: "\u76ee  \u5f55", bold: true, size: 32, color: PAL.primary, font: FONT_HEAD })],
});
const tocField = new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" });
const tocHint = new Paragraph({
  spacing: { before: 200, line: 312 },
  children: [new TextRun({
    text: "\u8bf4\u660e\uff1a\u672c\u76ee\u5f55\u7531\u57df\u4ee3\u7801\u751f\u6210\uff0c\u7f16\u8f91\u6587\u6863\u540e\u8bf7\u53f3\u952e\u76ee\u5f55\u9009\u62e9\u201c\u66f4\u65b0\u57df\u201d\u4ee5\u5237\u65b0\u9875\u7801\u3002",
    italics: true, size: 18, color: "888888", font: FONT_BODY,
  })],
});
frontChildren.push(tocTitle, tocField, tocHint);

const numberingConfig = allNumbering.map((ref) => ({
  reference: ref,
  levels: [{
    level: 0,
    format: LevelFormat.DECIMAL,
    text: "%1.",
    alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 720, hanging: 360 } } },
  }],
}));

function pageNumFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { line: 312 },
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "666666", font: FONT_BODY })],
    })],
  });
}

const docHeader = new Header({
  children: [new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { line: 312 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: PAL.table.innerLine, space: 4 } },
    children: [new TextRun({
      text: "Python \u5168\u6808\u9762\u8bd5\u590d\u4e60\u624b\u518c",
      size: 18, color: "888888", font: FONT_BODY,
    })],
  })],
});

const pgSize = { width: 11906, height: 16838 };
const pgMargin = { top: 1440, bottom: 1440, left: 1701, right: 1417 };

const doc = new Document({
  creator: "Interview Prep",
  title: "Python \u5168\u6808\u9762\u8bd5\u590d\u4e60\u624b\u518c",
  styles: {
    default: {
      document: {
        run: { font: FONT_BODY, size: 24, color: "000000" },
        paragraph: { spacing: { line: 312 } },
      },
      heading1: {
        run: { font: FONT_HEAD, size: 32, bold: true, color: PAL.primary },
        paragraph: { spacing: { before: 400, after: 200, line: 312 }, alignment: AlignmentType.CENTER },
      },
      heading2: {
        run: { font: FONT_HEAD, size: 30, bold: true, color: PAL.primary },
        paragraph: { spacing: { before: 320, after: 140, line: 312 } },
      },
      heading3: {
        run: { font: FONT_HEAD, size: 28, bold: true, color: PAL.primary },
        paragraph: { spacing: { before: 260, after: 110, line: 312 } },
      },
      heading4: {
        run: { font: FONT_HEAD, size: 26, bold: true, color: PAL.primary },
        paragraph: { spacing: { before: 220, after: 90, line: 312 } },
      },
    },
  },
  numbering: { config: numberingConfig },
  sections: [
    {
      properties: { page: { size: pgSize, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
      children: buildCoverR1({
        title: SPEC ? SPEC.title : "Python \u5168\u6808\u9762\u8bd5\u590d\u4e60\u624b\u518c",
        subtitle: SPEC ? SPEC.subtitle : "\u9762\u5411\u7855\u58eb\u5b66\u5386\u4e0e\u5341\u5e74\u7ecf\u9a8c\u5de5\u7a0b\u5e08\u7684\u7cfb\u7edf\u6027\u6280\u672f\u590d\u4e60",
        englishLabel: SPEC ? SPEC.englishLabel : "INTERVIEW HANDBOOK",
        metaLines: SPEC ? SPEC.metaLines : [
          "\u9002\u7528\u5c42\u7ea7\uff1a\u9ad8\u7ea7 / \u8d44\u6df1 Python \u5de5\u7a0b\u5e08",
          "\u77e5\u8bc6\u8303\u56f4\uff1a\u8bed\u8a00\u5185\u6838 \u00b7 \u5e76\u53d1\u5f02\u6b65 \u00b7 Web \u5f00\u53d1 \u00b7 \u6570\u636e\u5e93\u7f13\u5b58 \u00b7 \u5de5\u7a0b\u5316",
          "\u7f16\u5236\u65f6\u95f4\uff1a2026 \u5e74 10 \u6708",
        ],
        footerLeft: SPEC ? SPEC.footerLeft : "PYTHON INTERVIEW HANDBOOK",
        footerRight: SPEC ? SPEC.footerRight : "2026.10",
        palette: PAL,
      }),
    },
    {
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN } },
      },
      footers: { default: pageNumFooter() },
      children: frontChildren,
    },
    {
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } },
      },
      headers: { default: docHeader },
      footers: { default: pageNumFooter() },
      children: bodyChildren,
    },
  ],
});

const OUT = path.join(__dirname, "..", SPEC ? SPEC.out : "Python\u5168\u6808\u9762\u8bd5\u590d\u4e60\u624b\u518c.docx");
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("WROTE " + OUT + " (" + buf.length + " bytes)");
});
