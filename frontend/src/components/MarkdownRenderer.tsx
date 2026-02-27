import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import "katex/dist/katex.min.css";
// KaTeX copy-tex keeps formula selections copyable as LaTeX in mixed text.
import "katex/dist/contrib/copy-tex.mjs";
import {
  Fragment,
  isValidElement,
  useEffect,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

interface MarkdownRendererProps {
  content: string;
}

type FlowDiagramItem = {
  title: string;
  caption: string;
};

type LayerPipelineColumn = {
  heading: string;
  main: string;
  caption: string;
};

type LayerPipelineStructuredBlock = {
  kind: "layer_pipeline";
  columns: LayerPipelineColumn[];
  samples: string[];
};

type NeuronRuleCard = {
  title: string;
  weightLine: string | null;
  detailLines: string[];
};

type NeuronRulesStructuredBlock = {
  kind: "neuron_rules";
  intro: string[];
  cards: NeuronRuleCard[];
};

type VectorComparisonRow = {
  value: string;
  label: string;
};

type VectorComparisonStructuredBlock = {
  kind: "vector_comparison";
  intro: string[];
  rows: VectorComparisonRow[];
  outro: string[];
};

type ConfidencePointerStructuredBlock = {
  kind: "confidence_pointer";
  intro: string[];
  vectorLine: string;
  pointerLine: string;
  noteLine: string;
  outro: string[];
};

type StructuredCodeBlock =
  | LayerPipelineStructuredBlock
  | NeuronRulesStructuredBlock
  | VectorComparisonStructuredBlock
  | ConfidencePointerStructuredBlock;

const COPY_BUTTON_RESET_MS = 1800;

const LANGUAGE_LABELS: Record<string, string> = {
  bash: "Bash",
  c: "C",
  cpp: "C++",
  csharp: "C#",
  css: "CSS",
  html: "HTML",
  java: "Java",
  javascript: "JavaScript",
  js: "JavaScript",
  json: "JSON",
  jsx: "JSX",
  markdown: "Markdown",
  md: "Markdown",
  plaintext: "Plain text",
  py: "Python",
  python: "Python",
  sh: "Shell",
  shell: "Shell",
  sql: "SQL",
  text: "Plain text",
  ts: "TypeScript",
  tsx: "TSX",
  typescript: "TypeScript",
  yaml: "YAML",
  yml: "YAML",
};

/**
 * Replace `|` with `\vert` inside inline math spans (`$...$`) that sit on
 * lines which look like GFM table rows (start with `|`). This prevents the
 * pipe from being consumed as a column separator before the math plugin runs.
 */
function escapePipesInTableMath(md: string): string {
  return md.replace(/^(\|.*)/gm, (row) =>
    row.replace(/\$([^$]+)\$/g, (_match, expr: string) =>
      `$${expr.replace(/\|/g, "\\vert ")}$`,
    ),
  );
}

function isEscaped(text: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}

function isDoubleDollarAt(text: string, index: number): boolean {
  return (
    index >= 0 &&
    index < text.length - 1 &&
    text[index] === "$" &&
    text[index + 1] === "$" &&
    !isEscaped(text, index)
  );
}

function isSingleDollarAt(text: string, index: number): boolean {
  return (
    index >= 0 &&
    index < text.length &&
    text[index] === "$" &&
    text[index + 1] !== "$" &&
    !isEscaped(text, index)
  );
}

function findClosingDoubleDollar(text: string, fromIndex: number): number {
  for (let cursor = fromIndex; cursor < text.length - 1; cursor += 1) {
    if (isDoubleDollarAt(text, cursor)) {
      return cursor;
    }
  }
  return -1;
}

function findClosingSingleDollar(text: string, fromIndex: number, maxIndex: number): number {
  for (let cursor = fromIndex; cursor < maxIndex; cursor += 1) {
    if (isDoubleDollarAt(text, cursor)) {
      cursor += 1;
      continue;
    }
    if (isSingleDollarAt(text, cursor)) {
      return cursor;
    }
  }
  return -1;
}

function isLikelyBrokenDisplayMath(body: string): boolean {
  const trimmed = body.trim();
  if (!trimmed) {
    return true;
  }

  // Only treat strong markdown signals as broken display maths.
  // List-like `+` / `-` patterns are valid in many equations.
  const markdownSignals =
    /(^|\n)\s{0,3}#{1,6}\s|\*\*|`{1,3}|(^|\n)\s*---+\s*($|\n)/m;
  if (markdownSignals.test(trimmed)) {
    return true;
  }

  const looksNarrative =
    trimmed.length > 420 &&
    /[A-Za-z\u4e00-\u9fff]/.test(trimmed) &&
    /[。！？;；]/.test(trimmed);
  return looksNarrative;
}

function isLikelyBrokenInlineMath(body: string): boolean {
  const trimmed = body.trim();
  if (!trimmed) {
    return true;
  }

  if (trimmed.includes("\n") || trimmed.length > 120) {
    return true;
  }

  // Keep inline maths permissive; only obvious markdown artefacts are blocked.
  const markdownSignals = /\*\*|`{1,3}|^\s*#{1,6}\s/;
  return markdownSignals.test(trimmed);
}

/**
 * AI/OCR content can contain malformed `$` and `$$` fragments. When that
 * happens, the markdown math parser may swallow long narrative sections and
 * show red KaTeX error text. We defensively escape suspicious delimiters so
 * prose still renders as normal markdown.
 */
function sanitiseMalformedMathDelimiters(md: string): string {
  let output = "";
  let cursor = 0;

  while (cursor < md.length) {
    if (isDoubleDollarAt(md, cursor)) {
      const closeIndex = findClosingDoubleDollar(md, cursor + 2);
      if (closeIndex === -1) {
        output += "\\$\\$";
        cursor += 2;
        continue;
      }

      const body = md.slice(cursor + 2, closeIndex);
      if (isLikelyBrokenDisplayMath(body)) {
        output += `\\$\\$${body}\\$\\$`;
      } else {
        output += `$$${body}$$`;
      }
      cursor = closeIndex + 2;
      continue;
    }

    if (isSingleDollarAt(md, cursor)) {
      const lineBreak = md.indexOf("\n", cursor + 1);
      const searchEnd = lineBreak === -1 ? md.length : lineBreak;
      const closeIndex = findClosingSingleDollar(md, cursor + 1, searchEnd);
      if (closeIndex === -1) {
        output += "\\$";
        cursor += 1;
        continue;
      }

      const body = md.slice(cursor + 1, closeIndex);
      if (isLikelyBrokenInlineMath(body)) {
        output += `\\$${body}\\$`;
      } else {
        output += `$${body}$`;
      }
      cursor = closeIndex + 1;
      continue;
    }

    output += md[cursor];
    cursor += 1;
  }

  return output;
}

function normaliseSourceLines(source: string): string[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  while (lines.length > 0 && lines[0].trim().length === 0) {
    lines.shift();
  }
  while (lines.length > 0 && lines[lines.length - 1].trim().length === 0) {
    lines.pop();
  }
  return lines;
}

/**
 * Parse a strict two-line flow explanation:
 * line 1: stages separated by `->` or `→`
 * line 2: bracketed captions, one per stage (e.g. `(pixels)` or `（像素）`)
 */
function parseFlowExplanation(source: string): FlowDiagramItem[] | null {
  if (source.includes("```")) {
    return null;
  }

  const lines = normaliseSourceLines(source);
  if (lines.length !== 2) {
    return null;
  }

  const [titlesLine, captionsLine] = lines.map((line) => line.trim());
  if (!titlesLine || !captionsLine) {
    return null;
  }

  if (!/(?:->|→)/.test(titlesLine)) {
    return null;
  }

  const titles = titlesLine.split(/\s*(?:->|→)\s*/).map((part) => part.trim());
  if (titles.length < 2 || titles.some((title) => title.length === 0)) {
    return null;
  }

  const captions = parseBracketCaptionsLine(captionsLine);
  if (!captions || captions.length !== titles.length) {
    return null;
  }

  return titles.map((title, index) => ({
    title,
    caption: captions[index],
  }));
}

function parseBracketCaptionsLine(line: string): string[] | null {
  const text = line.trim();
  if (!text) {
    return null;
  }

  const captions: string[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    while (cursor < text.length && /\s/.test(text[cursor])) {
      cursor += 1;
    }
    if (cursor >= text.length) {
      break;
    }

    const open = text[cursor];
    const close = open === "(" ? ")" : open === "（" ? "）" : "";
    if (!close) {
      return null;
    }

    const closeIndex = text.indexOf(close, cursor + 1);
    if (closeIndex === -1) {
      return null;
    }

    const inner = text.slice(cursor + 1, closeIndex);
    if (!inner.trim() || /[()（）]/.test(inner)) {
      return null;
    }

    captions.push(text.slice(cursor, closeIndex + 1));
    cursor = closeIndex + 1;
  }

  return captions.length > 0 ? captions : null;
}

function parseLooseBracketCaptions(line: string, expectedCount: number): string[] | null {
  const text = line.trim();
  if (!text) {
    return null;
  }

  const matches = text.match(/[（(][^()（）]+[)）]/g);
  if (!matches || matches.length !== expectedCount) {
    return null;
  }

  const residue = text
    .replace(/[（(][^()（）]+[)）]/g, "")
    .replace(/[\s→|-]/g, "");
  if (residue.length > 0) {
    return null;
  }

  return matches.map((item) => item.trim());
}

/**
 * Only plain text and hard line breaks are eligible for smart flow parsing.
 * Any richer inline markup falls back to normal paragraph rendering.
 */
function extractPlainTextWithBreaks(node: ReactNode): string | null {
  if (node == null || typeof node === "boolean") {
    return "";
  }

  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  if (Array.isArray(node)) {
    let result = "";
    for (const child of node) {
      const chunk = extractPlainTextWithBreaks(child);
      if (chunk == null) {
        return null;
      }
      result += chunk;
    }
    return result;
  }

  if (isValidElement<{ children?: ReactNode }>(node)) {
    if (node.type === "br") {
      return "\n";
    }
    if (node.type === Fragment) {
      return extractPlainTextWithBreaks(node.props.children);
    }
    return null;
  }

  return null;
}

function countArrowSeparators(line: string): number {
  return (line.match(/(?:->|→)/g) ?? []).length;
}

function parseArrowSegments(line: string): string[] {
  return line
    .trim()
    .split(/\s*(?:->|→)\s*/)
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

function splitByWideSpacing(line: string): string[] {
  return line
    .trim()
    .split(/(?:\s{2,}|\t+)/)
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
}

/**
 * Many AI-generated diagrams use spacing to align columns.
 * We normalise common layer pipelines into stable grid columns.
 */
function parseLayerPipelineBlock(source: string): LayerPipelineStructuredBlock | null {
  const lines = normaliseSourceLines(source);
  if (lines.length < 2) {
    return null;
  }

  const arrowIndex = lines.findIndex((line) => countArrowSeparators(line) >= 2);
  if (arrowIndex < 0) {
    return null;
  }

  const mainSegments = parseArrowSegments(lines[arrowIndex]);
  if (mainSegments.length < 3) {
    return null;
  }

  let headings: string[] | null = null;
  for (let index = arrowIndex - 1; index >= 0; index -= 1) {
    const candidate = lines[index].trim();
    if (!candidate) {
      continue;
    }

    const parsed = splitByWideSpacing(candidate);
    if (parsed.length === mainSegments.length) {
      headings = parsed;
    }
    break;
  }

  let captions: string[] | null = null;
  let captionIndex = -1;
  for (let index = arrowIndex + 1; index < lines.length; index += 1) {
    const candidate = lines[index].trim();
    if (!candidate) {
      continue;
    }

    const parsed = parseLooseBracketCaptions(candidate, mainSegments.length);
    if (parsed) {
      captions = parsed;
      captionIndex = index;
    }
    break;
  }

  if (!headings && !captions) {
    return null;
  }

  const sampleStart = (captionIndex >= 0 ? captionIndex : arrowIndex) + 1;
  const samples = lines
    .slice(sampleStart)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0);

  return {
    kind: "layer_pipeline",
    columns: mainSegments.map((main, index) => ({
      heading: headings?.[index] ?? "",
      main,
      caption: captions?.[index] ?? "",
    })),
    samples,
  };
}

/**
 * This parser captures repeated "Neuron N learned..." sections and turns
 * them into cards so line wrapping no longer breaks the structure.
 */
function parseNeuronRuleBlock(source: string): NeuronRulesStructuredBlock | null {
  const lines = normaliseSourceLines(source);
  if (lines.length < 2) {
    return null;
  }

  const headingPattern = /^(第\s*\d+\s*个神经元[^：:]*[：:]|Neuron\s*\d+[^:]*:)\s*(.*)$/i;

  const intro: string[] = [];
  const cards: NeuronRuleCard[] = [];
  let currentCard: NeuronRuleCard | null = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }

    const headingMatch = line.match(headingPattern);
    if (headingMatch) {
      if (currentCard) {
        cards.push(currentCard);
      }

      const headingPrefix = headingMatch[1].trim();
      const headingTail = headingMatch[2].trim();
      currentCard = {
        title: headingTail ? `${headingPrefix} ${headingTail}` : headingPrefix,
        weightLine: null,
        detailLines: [],
      };
      continue;
    }

    if (!currentCard) {
      intro.push(line);
      continue;
    }

    const normalisedLine = line.replace(/^[-•]\s*/, "");
    if (/^(权重|weights?)[：:]/i.test(normalisedLine) && !currentCard.weightLine) {
      currentCard.weightLine = normalisedLine;
    } else {
      currentCard.detailLines.push(normalisedLine);
    }
  }

  if (currentCard) {
    cards.push(currentCard);
  }

  if (cards.length === 0) {
    return null;
  }

  const hasRealDetail = cards.some(
    (card) => card.weightLine !== null || card.detailLines.length > 0,
  );
  if (!hasRealDetail) {
    return null;
  }

  return {
    kind: "neuron_rules",
    intro,
    cards,
  };
}

function looksLikeVectorRowValue(value: string): boolean {
  return /\[[^\]]+\]/.test(value) || /(?:\d+(?:\.\d+)?\s+){2,}\d/.test(value);
}

function parseVectorComparisonBlock(source: string): VectorComparisonStructuredBlock | null {
  const lines = normaliseSourceLines(source);
  if (lines.length < 2) {
    return null;
  }

  const parsedRows: Array<{ index: number; row: VectorComparisonRow }> = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) {
      continue;
    }

    const match = line.match(/^(.*?)\s*(?:<-|←)\s*(.+)$/);
    if (!match) {
      continue;
    }

    const value = match[1].trim();
    const label = match[2].trim();
    if (!value || !label) {
      continue;
    }

    parsedRows.push({
      index,
      row: { value, label },
    });
  }

  if (parsedRows.length < 2 || !parsedRows.every((item) => looksLikeVectorRowValue(item.row.value))) {
    return null;
  }

  const firstIndex = parsedRows[0].index;
  const lastIndex = parsedRows[parsedRows.length - 1].index;

  return {
    kind: "vector_comparison",
    intro: lines.slice(0, firstIndex).map((line) => line.trim()).filter((line) => line.length > 0),
    rows: parsedRows.map((item) => item.row),
    outro: lines.slice(lastIndex + 1).map((line) => line.trim()).filter((line) => line.length > 0),
  };
}

function parseConfidencePointerBlock(source: string): ConfidencePointerStructuredBlock | null {
  const lines = normaliseSourceLines(source);
  if (lines.length < 3) {
    return null;
  }

  for (let index = 0; index <= lines.length - 3; index += 1) {
    const vectorLine = lines[index].trim();
    const pointerLine = lines[index + 1].trim();
    const noteLine = lines[index + 2].trim();

    if (!/\[[^\]]+\]/.test(vectorLine)) {
      continue;
    }

    if (!/^[↑|^]+$/.test(pointerLine) || !noteLine) {
      continue;
    }

    return {
      kind: "confidence_pointer",
      intro: lines.slice(0, index).map((line) => line.trim()).filter((line) => line.length > 0),
      vectorLine,
      pointerLine,
      noteLine,
      outro: lines
        .slice(index + 3)
        .map((line) => line.trim())
        .filter((line) => line.length > 0),
    };
  }

  return null;
}

function parseStructuredCodeBlock(source: string): StructuredCodeBlock | null {
  return (
    parseLayerPipelineBlock(source) ??
    parseNeuronRuleBlock(source) ??
    parseVectorComparisonBlock(source) ??
    parseConfidencePointerBlock(source)
  );
}

function formatLanguageTag(language?: string): string {
  if (!language) {
    return "Plain text";
  }

  const normalised = language.trim().toLowerCase();
  if (!normalised) {
    return "Plain text";
  }

  const mapped = LANGUAGE_LABELS[normalised];
  if (mapped) {
    return mapped;
  }

  return normalised
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (char) => char.toUpperCase());
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to a legacy copy path.
    }
  }

  if (typeof document === "undefined") {
    return false;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
}

function CopyableCodePanel({
  codeText,
  markerLabel,
  children,
}: {
  codeText: string;
  markerLabel: string;
  children: ReactNode;
}) {
  const [isCopied, setIsCopied] = useState(false);

  useEffect(() => {
    if (!isCopied) {
      return;
    }

    const timerId = window.setTimeout(() => {
      setIsCopied(false);
    }, COPY_BUTTON_RESET_MS);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [isCopied]);

  const handleCopy = async () => {
    const copied = await copyTextToClipboard(codeText);
    if (copied) {
      setIsCopied(true);
    }
  };
  const copyLabel = isCopied ? "Copied" : "Copy";

  return (
    <div className="markdown-code-panel my-3">
      <div className="markdown-panel-controls">
        <span className="markdown-panel-marker" aria-label="Code type and language">
          {markerLabel}
        </span>
        <button
          type="button"
          onClick={() => {
            void handleCopy();
          }}
          className="markdown-panel-copy-btn"
          title={copyLabel}
          aria-label={isCopied ? "Code copied to clipboard" : "Copy code block"}
        >
          {copyLabel}
        </button>
      </div>
      <div className="markdown-code-content">{children}</div>
    </div>
  );
}

function FlowExplanationDiagram({
  items,
  embedded = false,
}: {
  items: FlowDiagramItem[];
  embedded?: boolean;
}) {
  return (
    <div
      className={`markdown-flow-wrap${embedded ? " markdown-flow-embedded" : ""}`}
      role="group"
      aria-label="Flow explanation diagram"
    >
      <div className="markdown-flow-track">
        {items.map((item, index) => (
          <Fragment key={`${item.title}-${item.caption}-${index}`}>
            {index > 0 && (
              <div className="markdown-flow-arrow" aria-hidden="true">
                →
              </div>
            )}
            <div className="markdown-flow-node">
              <div className="markdown-flow-title">{item.title}</div>
              <div className="markdown-flow-caption">{item.caption}</div>
            </div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function StructuredCodeBlockView({ block }: { block: StructuredCodeBlock }) {
  if (block.kind === "layer_pipeline") {
    return (
      <div className="markdown-structured-panel markdown-structured-pipeline" aria-label="Layer pipeline explanation">
        <div className="markdown-pipeline-track">
          {block.columns.map((column, index) => (
            <Fragment key={`${column.heading}-${column.main}-${column.caption}-${index}`}>
              {index > 0 && (
                <div className="markdown-pipeline-arrow" aria-hidden="true">
                  →
                </div>
              )}
              <div className="markdown-pipeline-column">
                {column.heading && <div className="markdown-pipeline-heading">{column.heading}</div>}
                <div className="markdown-pipeline-main">{column.main}</div>
                {column.caption && <div className="markdown-pipeline-caption">{column.caption}</div>}
              </div>
            </Fragment>
          ))}
        </div>

        {block.samples.length > 0 && (
          <pre className="markdown-pipeline-samples">
            <code>{block.samples.join("\n")}</code>
          </pre>
        )}
      </div>
    );
  }

  if (block.kind === "neuron_rules") {
    return (
      <div className="markdown-structured-panel markdown-structured-neurons" aria-label="Neuron rule explanation">
        {block.intro.length > 0 && (
          <div className="markdown-structured-intro">
            {block.intro.map((line, index) => (
              <p key={`${line}-${index}`}>{line}</p>
            ))}
          </div>
        )}

        <div className="markdown-neuron-grid">
          {block.cards.map((card, index) => (
            <section key={`${card.title}-${index}`} className="markdown-neuron-card">
              <h4 className="markdown-neuron-title">{card.title}</h4>
              {card.weightLine && <p className="markdown-neuron-weight">{card.weightLine}</p>}
              {card.detailLines.map((line, lineIndex) => (
                <p key={`${line}-${lineIndex}`} className="markdown-neuron-detail">
                  {line}
                </p>
              ))}
            </section>
          ))}
        </div>
      </div>
    );
  }

  if (block.kind === "vector_comparison") {
    return (
      <div className="markdown-structured-panel markdown-structured-vectors" aria-label="Vector comparison explanation">
        {block.intro.length > 0 && (
          <div className="markdown-structured-intro">
            {block.intro.map((line, index) => (
              <p key={`${line}-${index}`}>{line}</p>
            ))}
          </div>
        )}

        <div className="markdown-vector-rows">
          {block.rows.map((row, index) => (
            <div key={`${row.value}-${row.label}-${index}`} className="markdown-vector-row">
              <code className="markdown-vector-value">{row.value}</code>
              <span className="markdown-vector-label">{row.label}</span>
            </div>
          ))}
        </div>

        {block.outro.length > 0 && (
          <div className="markdown-structured-outro">
            {block.outro.map((line, index) => (
              <p key={`${line}-${index}`}>{line}</p>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="markdown-structured-panel markdown-structured-confidence" aria-label="Prediction confidence explanation">
      {block.intro.length > 0 && (
        <div className="markdown-structured-intro">
          {block.intro.map((line, index) => (
            <p key={`${line}-${index}`}>{line}</p>
          ))}
        </div>
      )}

      <div className="markdown-confidence-vector">
        <code>{block.vectorLine}</code>
      </div>
      <div className="markdown-confidence-pointer" aria-hidden="true">
        {block.pointerLine}
      </div>
      <p className="markdown-confidence-note">{block.noteLine}</p>

      {block.outro.length > 0 && (
        <div className="markdown-structured-outro">
          {block.outro.map((line, index) => (
            <p key={`${line}-${index}`}>{line}</p>
          ))}
        </div>
      )}
    </div>
  );
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const processed = escapePipesInTableMath(sanitiseMalformedMathDelimiters(content));

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({
            inline,
            className,
            children,
            ...props
          }: ComponentPropsWithoutRef<"code"> & { inline?: boolean }) {
            const match = /language-([^\s]+)/.exec(className || "");
            const codeString = String(children).replace(/\n$/, "");
            const language = match?.[1];
            const languageTag = formatLanguageTag(language);
            const plainTextTag = formatLanguageTag();
            const isCompactPlainBlock =
              !language &&
              !codeString.includes("\n") &&
              codeString.trim().length > 0 &&
              codeString.trim().length <= 64;
            const structuredBlock = !language ? parseStructuredCodeBlock(codeString) : null;
            const flowItems = !language ? parseFlowExplanation(codeString) : null;

            if (!inline) {
              if (isCompactPlainBlock) {
                return (
                  <code className="markdown-short-block-code font-mono text-[0.95rem]">
                    {codeString}
                  </code>
                );
              }

              if (structuredBlock) {
                return (
                  <CopyableCodePanel codeText={codeString} markerLabel={`Code: ${plainTextTag}`}>
                    <StructuredCodeBlockView block={structuredBlock} />
                  </CopyableCodePanel>
                );
              }

              if (flowItems) {
                return (
                  <CopyableCodePanel codeText={codeString} markerLabel={`Code: ${plainTextTag}`}>
                    <FlowExplanationDiagram items={flowItems} embedded />
                  </CopyableCodePanel>
                );
              }

              if (!language) {
                return (
                  <CopyableCodePanel codeText={codeString} markerLabel={`Code: ${plainTextTag}`}>
                    <pre className="markdown-plain-code overflow-x-auto px-3 py-2">
                      <code className="font-mono text-[0.9rem] leading-6">{codeString}</code>
                    </pre>
                  </CopyableCodePanel>
                );
              }

              return (
                <CopyableCodePanel codeText={codeString} markerLabel={`Code: ${languageTag}`}>
                  <div className="markdown-code-block overflow-x-auto">
                    <SyntaxHighlighter
                      style={oneLight}
                      language={language}
                      PreTag="div"
                      wrapLongLines
                      codeTagProps={{
                        style: {
                          background: "transparent",
                          fontSize: "inherit",
                          lineHeight: "inherit",
                          padding: 0,
                        },
                      }}
                      customStyle={{
                        margin: 0,
                        borderRadius: 0,
                        fontSize: "0.9rem",
                        lineHeight: "1.6",
                        padding: "0.7rem 0.85rem",
                        background: "transparent",
                      }}
                    >
                      {codeString}
                    </SyntaxHighlighter>
                  </div>
                </CopyableCodePanel>
              );
            }

            return (
              <code
                className="rounded-md border px-1.5 py-0.5 font-mono text-[0.88em]"
                {...props}
              >
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="markdown-table-wrap my-5 overflow-x-auto rounded-xl border shadow-sm">
                <table className="w-full border-collapse text-sm">{children}</table>
              </div>
            );
          },
          thead({ children }) {
            return <thead className="text-brand">{children}</thead>;
          },
          tbody({ children }) {
            return <tbody>{children}</tbody>;
          },
          tr({ children }) {
            return (
              <tr className="transition-colors odd:bg-white even:bg-[var(--markdown-table-row-alt)] hover:bg-[var(--markdown-table-row-hover)]">
                {children}
              </tr>
            );
          },
          th({ children }) {
            return (
              <th className="border-b px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.12em]">
                {children}
              </th>
            );
          },
          td({ children }) {
            return <td className="px-4 py-3 align-top text-left">{children}</td>;
          },
          p({ children }) {
            const paragraphText = extractPlainTextWithBreaks(children);
            const flowItems = paragraphText ? parseFlowExplanation(paragraphText) : null;

            if (flowItems) {
              return <FlowExplanationDiagram items={flowItems} />;
            }

            return <p className="mb-3 leading-relaxed last:mb-0">{children}</p>;
          },
          ul({ children }) {
            return <ul className="mb-4 list-disc space-y-1.5 pl-6">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="mb-4 list-decimal space-y-1.5 pl-6">{children}</ol>;
          },
          li({ children }) {
            return <li className="leading-relaxed">{children}</li>;
          },
          h1({ children }) {
            return (
              <h1 className="mt-6 mb-3 text-xl font-semibold tracking-[0.01em] text-brand">
                {children}
              </h1>
            );
          },
          h2({ children }) {
            return (
              <h2 className="mt-5 mb-2.5 text-lg font-semibold tracking-[0.01em] text-brand">
                {children}
              </h2>
            );
          },
          h3({ children }) {
            return (
              <h3 className="mt-4 mb-2 text-base font-semibold tracking-[0.01em] text-brand">
                {children}
              </h3>
            );
          },
          hr() {
            return <hr className="my-6 border-t" />;
          },
          blockquote({ children }) {
            return (
              <blockquote className="mb-4 rounded-r-lg border-l-4 py-2 pr-3 pl-4">
                {children}
              </blockquote>
            );
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="font-medium underline decoration-2 underline-offset-2 transition-colors"
              >
                {children}
              </a>
            );
          },
          strong({ children }) {
            return <strong className="font-semibold text-brand">{children}</strong>;
          },
          em({ children }) {
            return <em className="italic text-[var(--markdown-text-strong)]">{children}</em>;
          },
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}
