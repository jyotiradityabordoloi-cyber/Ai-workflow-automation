import type { Analysis, ReviewFlag } from "./types";

// Module 4 safety rules. In the mock phase they run in the browser; from step 2 the
// FastAPI backend is the source of truth and the UI only displays the flags it returns.

export const CONFIDENCE_THRESHOLD = 0.7;
export const MANAGER_KEYWORDS = ["legal", "lawyer", "refund", "chargeback"];

const keywordRe = new RegExp(`\\b(${MANAGER_KEYWORDS.join("|")})\\w*`, "gi");

export function detectLanguageIssue(text: string): string | null {
  const letters = [...text].filter((c) => /\p{L}/u.test(c));
  if (letters.length === 0) return "No readable text";
  const nonLatin = letters.filter((c) => c.codePointAt(0)! > 0x24f).length / letters.length;
  if (nonLatin > 0.3) return "Unsupported language (non-Latin script)";
  if (text.trim().split(/\s+/).length < 4) return "Too short to classify reliably";
  return null;
}

export function managerKeywords(text: string): string[] {
  return [...new Set([...text.matchAll(keywordRe)].map((m) => m[1].toLowerCase()))];
}

export function computeFlags(text: string, a: Pick<Analysis, "confidence" | "priority" | "sentiment">): ReviewFlag[] {
  const flags: ReviewFlag[] = [];
  const lang = detectLanguageIssue(text);
  if (lang) flags.push({ type: "manual_review", reason: lang });
  else if (a.confidence < CONFIDENCE_THRESHOLD)
    flags.push({ type: "manual_review", reason: `Confidence ${a.confidence.toFixed(2)} is below ${CONFIDENCE_THRESHOLD}` });
  if (a.sentiment === "angry" && a.priority === "P1")
    flags.push({ type: "senior_agent", reason: "Angry customer on a P1 ticket" });
  const kw = managerKeywords(text);
  if (kw.length) flags.push({ type: "manager_review", reason: `Mentions ${kw.join(", ")}` });
  return flags;
}

export const hasFlag = (flags: ReviewFlag[] | undefined, t: ReviewFlag["type"]) => !!flags?.some((f) => f.type === t);
