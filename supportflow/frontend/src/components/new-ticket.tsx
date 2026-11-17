"use client";

import { Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Channel, Customer } from "@/lib/types";
import { useAction } from "@/lib/use-action";
import { Button, ErrorText } from "./ui";

const input = "h-9 w-full rounded-lg border border-line bg-subtle px-3 text-[13px]";
const label = "block text-xs font-medium text-muted";

/** Module 1 intake: create a ticket from a form and (optionally) classify it straight away. */
export function NewTicketButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}><Plus className="size-3.5" /> New ticket</Button>
      {open && <NewTicketDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function NewTicketDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const ref = useRef<HTMLDialogElement>(null);
  const [customer, setCustomer] = useState<Customer>({ name: "", company: "", email: "", plan: "Pro" });
  const [channel, setChannel] = useState<Channel>("email");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [analyze, setAnalyze] = useState(true);
  const create = useAction(async () => {
    const id = await api.createTicket({ subject, body, customer, channel, analyze });
    onClose();
    router.push(`/tickets/${id}`);
  });

  useEffect(() => {
    // No cleanup: closing in cleanup would fire `close` -> onClose under StrictMode's double effect run.
    // Unmounting the <dialog> removes it from the top layer anyway.
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  const valid = customer.name.trim() && body.trim();

  return (
    <dialog ref={ref} onClose={onClose} onCancel={onClose}
      className="m-auto w-[min(560px,calc(100vw-32px))] rounded-xl border border-line bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/40">
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); if (valid) create.run(); }}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold">New ticket</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-hover"><X className="size-4" /></button>
        </div>
        <div className="grid gap-3 px-5 py-4 sm:grid-cols-2">
          <label className={label}>Customer name *
            <input className={input} required value={customer.name} onChange={(e) => setCustomer({ ...customer, name: e.target.value })} maxLength={120} autoFocus />
          </label>
          <label className={label}>Company
            <input className={input} value={customer.company} onChange={(e) => setCustomer({ ...customer, company: e.target.value })} maxLength={160} />
          </label>
          <label className={label}>Email
            <input className={input} type="email" value={customer.email} onChange={(e) => setCustomer({ ...customer, email: e.target.value })} maxLength={200} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className={label}>Plan
              <select className={input} value={customer.plan} onChange={(e) => setCustomer({ ...customer, plan: e.target.value as Customer["plan"] })}>
                {["Starter", "Pro", "Business", "Enterprise"].map((p) => <option key={p}>{p}</option>)}
              </select>
            </label>
            <label className={label}>Channel
              <select className={input} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                <option value="email">Email</option><option value="chat">Chat</option><option value="web_form">Web form</option>
              </select>
            </label>
          </div>
          <label className={`${label} sm:col-span-2`}>Subject
            <input className={input} value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
          </label>
          <label className={`${label} sm:col-span-2`}>Message *
            <textarea className="w-full rounded-lg border border-line bg-subtle p-3 text-[13px]" rows={6} required value={body}
              onChange={(e) => setBody(e.target.value)} maxLength={5000} placeholder="Paste the customer's message" />
          </label>
          <label className="flex items-center gap-2 text-[13px] sm:col-span-2">
            <input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} />
            Classify immediately {api.mode === "live" ? "with the LLM" : "(mock heuristic)"}. The result still needs an agent&apos;s confirmation.
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">
          <ErrorText>{create.error}</ErrorText>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={!valid} loading={create.loading}>{analyze ? "Create & classify" : "Create ticket"}</Button>
        </div>
      </form>
    </dialog>
  );
}
