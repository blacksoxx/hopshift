import * as React from "react";
import { cn } from "@/lib/utils";

export type CodeLang = "hcl" | "json" | "markdown" | "shell" | "text";

const HIGHLIGHT_LIMIT = 200_000; // characters; larger files stay plain to keep the tab responsive
const THEMES = { light: "github-light", dark: "github-dark" } as const;
const LANGS: Exclude<CodeLang, "text">[] = ["hcl", "json", "markdown", "shell"];

type Highlighter = { codeToHtml: (code: string, options: { lang: string; themes: typeof THEMES; defaultColor: false }) => string };
let highlighterPromise: Promise<Highlighter> | null = null;

/**
 * One shared highlighter, created on first use. The JavaScript regex engine is used instead of
 * the default Oniguruma build because the API's Content-Security-Policy (`script-src 'self'`)
 * does not allow WebAssembly compilation.
 */
function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import("shiki").then(({ createHighlighter, createJavaScriptRegexEngine }) =>
      createHighlighter({ themes: [THEMES.light, THEMES.dark], langs: LANGS, engine: createJavaScriptRegexEngine({ forgiving: true }) }),
    );
    highlighterPromise.catch(() => {
      highlighterPromise = null;
    });
  }
  return highlighterPromise;
}

/** Pick a shiki language from a file name. */
export function languageFor(path: string): CodeLang {
  const name = path.toLowerCase();
  if (name.endsWith(".tf") || name.endsWith(".hcl") || name.endsWith(".tfvars")) return "hcl";
  if (name.endsWith(".json") || name.endsWith(".tfstate")) return "json";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "markdown";
  if (name.endsWith(".sh") || name.endsWith(".bash")) return "shell";
  return "text";
}

/**
 * Syntax-highlighted code. Renders a plain <pre> immediately (so the text is always present) and
 * swaps in shiki's dual-theme HTML once the bundle has loaded; globals.css switches the theme.
 */
export function CodeView({ code, lang = "text", className, testId, wrap = false }: { code: string; lang?: CodeLang; className?: string; testId?: string; wrap?: boolean }) {
  const [html, setHtml] = React.useState<string | null>(null);
  const highlight = lang !== "text" && code.length > 0 && code.length <= HIGHLIGHT_LIMIT;

  React.useEffect(() => {
    let cancelled = false;
    setHtml(null);
    if (!highlight) return;
    getHighlighter()
      .then((highlighter) => highlighter.codeToHtml(code, { lang, themes: THEMES, defaultColor: false }))
      .then((rendered) => {
        if (!cancelled) setHtml(rendered);
      })
      .catch((exc: unknown) => {
        // Plain text stays on screen; the reason is useful when a grammar or the wasm engine fails to load.
        console.warn("[CodeView] syntax highlighting unavailable:", exc);
      });
    return () => {
      cancelled = true;
    };
  }, [code, lang, highlight]);

  return (
    <div
      data-testid={testId}
      data-highlighted={html ? "true" : "false"}
      className={cn(
        "overflow-auto font-mono text-[12.5px] leading-relaxed [&_pre]:m-0 [&_pre]:min-w-max [&_pre]:p-4 [&_code]:block",
        wrap && "[&_pre]:min-w-0 [&_pre]:whitespace-pre-wrap [&_pre]:break-words",
        className,
      )}
    >
      {html ? (
        <div dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <pre className={cn("text-foreground/90", wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre")}>
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}
