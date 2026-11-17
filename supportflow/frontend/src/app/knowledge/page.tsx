"use client";

import { BookOpen, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/shell";
import { Badge, Card, CardHeader, CategoryBadge, EmptyState } from "@/components/ui";
import { api, useWorkspace } from "@/lib/api";
import { CATEGORIES, CATEGORY_LABEL, timeAgo } from "@/lib/format";
import type { Category, RetrievedDoc } from "@/lib/types";

export default function KnowledgePage() {
  const ws = useWorkspace();
  const [q, setQ] = useState("customer was charged twice for the subscription");
  const [results, setResults] = useState<RetrievedDoc[] | null>(null);
  const [cat, setCat] = useState<Category | "">("");

  useEffect(() => {
    let live = true;
    const h = setTimeout(() => {
      if (!q.trim()) { setResults(null); return; }
      api.searchKnowledge(q, 5).then((r) => live && setResults(r));
    }, 200);
    return () => { live = false; clearTimeout(h); };
  }, [q]);

  const docs = ws.knowledge.filter((d) => !cat || d.category === cat);

  return (
    <>
      <PageHeader title="Knowledge retrieval" subtitle="Resolved tickets the response assistant grounds its drafts in." />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader title="Test retrieval" hint="Type a customer message to see which resolved tickets would be retrieved, with similarity scores." />
            <div className="p-4">
              <label className="relative block">
                <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-faint" />
                <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Retrieval query"
                  className="h-10 w-full rounded-lg border border-line bg-subtle pr-3 pl-9 text-[14px]" placeholder="e.g. password reset email never arrives" />
              </label>
              <ol className="mt-3 space-y-2">
                {results?.length === 0 && <li className="text-[13px] text-muted">No resolved ticket shares meaningful terms with this query.</li>}
                {results?.map((r, i) => (
                  <li key={r.doc.id} className="rounded-lg border border-line p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-faint">#{i + 1}</span>
                      <span className="font-mono text-xs text-muted">{r.doc.id}</span>
                      <span className="text-[13px] font-medium">{r.doc.subject}</span>
                      <CategoryBadge c={r.doc.category} />
                      {r.doc.source === "ticket" && <Badge tone="accent">Learned</Badge>}
                      <span className="ml-auto flex w-32 items-center gap-2">
                        <span className="h-1.5 flex-1 rounded-full bg-subtle"><span className="block h-full rounded-full bg-accent" style={{ width: `${r.similarity * 100}%` }} /></span>
                        <span className="font-mono text-[11px] tabular-nums text-muted">{r.similarity.toFixed(2)}</span>
                      </span>
                    </div>
                    <p className="mt-1.5 text-[13px] text-muted">{r.doc.resolution}</p>
                  </li>
                ))}
              </ol>
            </div>
          </Card>

          <Card>
            <CardHeader title={`Resolved tickets (${docs.length})`}
              right={<select value={cat} onChange={(e) => setCat(e.target.value as Category | "")} aria-label="Filter category"
                className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]">
                <option value="">All categories</option>
                {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
              </select>} />
            {docs.length === 0 ? <EmptyState icon={<BookOpen className="size-6" />} title="No documents in this category" /> : (
              <ul className="divide-y divide-line">
                {docs.map((d) => (
                  <li key={d.id} className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted">{d.id}</span>
                      <span className="text-[13px] font-medium">{d.subject}</span>
                      <CategoryBadge c={d.category} />
                      {d.source === "ticket" && <Badge tone="accent">Learned{d.resolvedAt ? ` ${timeAgo(d.resolvedAt)}` : ""}</Badge>}
                    </div>
                    <p className="mt-1 text-[13px] text-muted">{d.resolution}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Index" />
            <dl className="space-y-2 p-4 text-[13px]">
              <div className="flex justify-between"><dt className="text-muted">Documents</dt><dd className="tabular-nums">{ws.knowledge.length}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Learned from resolved tickets</dt><dd className="tabular-nums">{ws.knowledge.filter((d) => d.source === "ticket").length}</dd></div>
              {CATEGORIES.map((c) => (
                <div key={c} className="flex justify-between"><dt className="text-muted">{CATEGORY_LABEL[c]}</dt><dd className="tabular-nums">{ws.knowledge.filter((d) => d.category === c).length}</dd></div>
              ))}
            </dl>
          </Card>
          <Card className="p-4 text-[13px]">
            <p className="font-medium">Retrieval method</p>
            {api.mode === "live" ? (
              <>
                <p className="mt-1 text-muted">Sentence embeddings (all-MiniLM-L6-v2, run locally) in a ChromaDB vector store, ranked by cosine similarity. Tickets show the top 3 above a 0.30 floor.</p>
                <p className="mt-1 text-muted">Resolving a ticket adds its fix here, so the next similar ticket finds it.</p>
              </>
            ) : (
              <p className="mt-1 text-muted">Mock mode: TF-IDF cosine similarity in the browser. Live mode uses embeddings in ChromaDB.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
