import type { KnowledgeDoc, RetrievedDoc } from "../types";

// Mock retrieval: TF-IDF cosine similarity over resolved tickets, computed in the browser.
// Step 3 replaces this with embedding search in a vector database behind the same API shape.

const STOP = new Set("a an and are as at be but by can do does for from has have i if in into is it its me my no not of on or our please so that the their them there they this to was we were what when which with you your us any all just still since get got".split(" "));

export function tokens(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]+/g) ?? [])
    .filter((t) => t.length > 1 && !STOP.has(t))
    .map((t) => t.replace(/(ing|ed|es|s)$/, (m) => (t.length > m.length + 3 ? "" : m)));
}

function vector(toks: string[], idf: Map<string, number>): Map<string, number> {
  const v = new Map<string, number>();
  for (const t of toks) v.set(t, (v.get(t) ?? 0) + 1);
  for (const [t, c] of v) v.set(t, c * (idf.get(t) ?? 0));
  return v;
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
  let dot = 0, na = 0, nb = 0;
  for (const [t, x] of a) { na += x * x; const y = b.get(t); if (y) dot += x * y; }
  for (const y of b.values()) nb += y * y;
  return na && nb ? dot / Math.sqrt(na * nb) : 0;
}

export function search(docs: KnowledgeDoc[], query: string, k = 3): RetrievedDoc[] {
  const docToks = docs.map((d) => tokens(`${d.subject} ${d.body} ${d.resolution}`));
  const df = new Map<string, number>();
  for (const toks of docToks) for (const t of new Set(toks)) df.set(t, (df.get(t) ?? 0) + 1);
  const idf = new Map([...df].map(([t, f]) => [t, Math.log(1 + docs.length / f)]));
  const q = vector(tokens(query), idf);
  return docs
    .map((doc, i) => ({ doc, similarity: Math.round(cosine(q, vector(docToks[i], idf)) * 100) / 100 }))
    .filter((r) => r.similarity > 0)
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, k);
}
