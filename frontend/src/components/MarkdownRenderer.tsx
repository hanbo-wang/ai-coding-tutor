import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import "katex/dist/katex.min.css";
import {
  Fragment,
  isValidElement,
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

/**
 * Replace `|` with `\vert` inside inline math spans (`$...$`) that sit on
 * lines which look like GFM table rows (start with `|`).  This prevents the
 * pipe from being consumed as a column separator before the math plugin runs.
 */
function escapePipesInTableMath(md: string): string {
  return md.replace(/^(\|.*)/gm, (row) =>
    row.replace(/\$([^$]+)\$/g, (_match, expr: string) =>
      `$${expr.replace(/\|/g, "\\vert ")}$`,
    ),
  );
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

  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  while (lines.length > 0 && lines[0].trim().length === 0) {
    lines.shift();
  }
  while (lines.length > 0 && lines[lines.length - 1].trim().length === 0) {
    lines.pop();
  }

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

function FlowExplanationDiagram({ items }: { items: FlowDiagramItem[] }) {
  return (
    <div
      className="markdown-flow-wrap"
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

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const processed = escapePipesInTableMath(content);

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
            const isSingleLinePlainSnippet =
              !language &&
              !codeString.includes("\n") &&
              codeString.trim().length > 0 &&
              codeString.trim().length <= 48;
            const flowItems = !language ? parseFlowExplanation(codeString) : null;

            if (!inline) {
              if (flowItems) {
                return <FlowExplanationDiagram items={flowItems} />;
              }

              if (isSingleLinePlainSnippet) {
                return (
                  <code className="markdown-short-block-code rounded-md border px-1.5 py-0.5 font-mono text-[0.88em]">
                    {codeString}
                  </code>
                );
              }

              if (!language) {
                return (
                  <pre className="markdown-plain-code my-3 overflow-x-auto rounded-md border px-3 py-2">
                    <code className="font-mono text-[0.9rem] leading-6">
                      {codeString}
                    </code>
                  </pre>
                );
              }

              return (
                <div className="markdown-code-block my-3 overflow-hidden rounded-lg border">
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
                <table className="w-full border-collapse text-sm">
                  {children}
                </table>
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
