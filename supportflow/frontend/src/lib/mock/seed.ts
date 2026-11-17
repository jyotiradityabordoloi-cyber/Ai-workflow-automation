import { computeFlags } from "../rules";
import type {
  Analysis, Category, Channel, Customer, Draft, Escalation, KnowledgeDoc, Priority, Sentiment, Ticket, TicketStatus, Workspace,
} from "../types";

// Realistic MOCK data for the frontend phase. The analyses below are hand-written stand-ins
// for model output, not results of a model, and are never used to report accuracy.

export const MOCK_MODEL = "mock-classifier (no LLM yet)";

const CUSTOMERS: Customer[] = [
  { name: "Maya Chen", company: "Northwind Studio", email: "maya@northwind.example", plan: "Pro" },
  { name: "Daniel Okafor", company: "Contoso Ltd", email: "daniel@contoso.example", plan: "Business" },
  { name: "Priya Raman", company: "Blue Yonder Media", email: "priya@blueyonder.example", plan: "Pro" },
  { name: "Lukas Weber", company: "Fabrikam Inc", email: "lukas@fabrikam.example", plan: "Business" },
  { name: "Sofia Alvarez", company: "Litware", email: "sofia@litware.example", plan: "Starter" },
  { name: "Ahmed Hassan", company: "Adventure Works", email: "ahmed@adventure.example", plan: "Business" },
  { name: "Grace Kim", company: "Tailspin Toys", email: "grace@tailspin.example", plan: "Enterprise" },
  { name: "Tom Becker", company: "Wingtip", email: "tom@wingtip.example", plan: "Pro" },
  { name: "Aisha Bello", company: "Coho Winery", email: "aisha@coho.example", plan: "Business" },
  { name: "Ravi Menon", company: "Proseware", email: "ravi@proseware.example", plan: "Starter" },
  { name: "Elena Rossi", company: "Datum Corp", email: "elena@datum.example", plan: "Enterprise" },
  { name: "Jonas Berg", company: "Lucerne Publishing", email: "jonas@lucerne.example", plan: "Pro" },
  { name: "Mei Tanaka", company: "Graphic Design Institute", email: "mei@gdi.example", plan: "Pro" },
  { name: "Carlos Diaz", company: "Grupo Lumen", email: "carlos@lumen.example", plan: "Pro" },
  { name: "Unknown sender", company: "—", email: "noreply@unknown.example", plan: "Starter" },
];

type A = [Category, Priority, Sentiment, number, string];
type Row = [id: string, minsAgo: number, cust: number, channel: Channel, subject: string, body: string, analysis: A | null, status: TicketStatus];

const ROWS: Row[] = [
  ["SF-1042", 6, 0, "email", "Charged twice this month", "I've been charged twice this month and I've sent 3 emails already. This is unacceptable.",
    ["billing", "P1", "angry", 0.94, "Customer reports a duplicate charge this month. Has contacted support three times without a resolution."], "needs_review"],
  ["SF-1041", 14, 1, "chat", "Dashboard returning 500 errors for the whole team", "The dashboard has been returning 500 errors for our whole team since 9am. We can't open any reports and we have a client demo at 2pm today.",
    ["bug", "P1", "frustrated", 0.91, "All users at Contoso get HTTP 500 on the dashboard since 9am. A client demo at 2pm is at risk."], "needs_review"],
  ["SF-1040", 22, 0, "email", "Final warning before chargeback", "If the duplicate charge isn't refunded by Friday I am filing a chargeback with my bank and handing this to my lawyer. Four emails and nobody has replied.",
    ["billing", "P1", "angry", 0.93, "Customer threatens a chargeback and legal action over an unrefunded duplicate charge. Four emails unanswered."], "needs_review"],
  ["SF-1039", 31, 2, "web_form", "Schedule exports to Google Drive", "Love the new export feature! Would be great if we could schedule exports to run weekly straight into Google Drive.",
    ["feature_request", "P3", "positive", 0.89, "Customer asks for scheduled weekly exports to Google Drive. Positive about the new export feature."], "needs_review"],
  ["SF-1038", 45, 14, "email", "(no subject)", "help",
    ["other", "P2", "neutral", 0.31, "Insufficient information to classify. Recommend manual review."], "needs_review"],
  ["SF-1037", 58, 13, "email", "Acceso", "No puedo iniciar sesión desde ayer, me dice que mi contraseña es incorrecta aunque la cambié.",
    ["account", "P2", "frustrated", 0.52, "Customer (Spanish) cannot log in since yesterday despite changing the password."], "needs_review"],
  ["SF-1036", 72, 6, "email", "Admin account possibly compromised", "We think someone got into our admin account: there are two API keys none of us created and a login from a country we don't operate in. Please lock it down right away.",
    ["account", "P1", "frustrated", 0.9, "Possible admin account compromise: unknown API keys and a foreign login. Customer asks for an immediate lockdown."], "in_progress"],
  ["SF-1035", 95, 4, "web_form", "CSV import fails at row 1,200", "CSV import keeps failing at row 1,200 with 'invalid date format' even though every date is YYYY-MM-DD. Smaller files import fine. Tried three times.",
    ["bug", "P2", "frustrated", 0.86, "Large CSV imports fail at row 1,200 with an invalid date format error. Smaller files work."], "needs_review"],
  ["SF-1034", 130, 5, "email", "Invoice with VAT number", "Can you send me the October invoice with our VAT number on it? Our finance team needs it for reconciliation.",
    ["billing", "P2", "neutral", 0.92, "Customer needs the October invoice reissued with their VAT number for reconciliation."], "awaiting_approval"],
  ["SF-1033", 160, 9, "chat", "Password reset email never arrives", "Password reset emails never arrive. I checked spam and tried four times today. I'm locked out.",
    ["account", "P2", "frustrated", 0.88, "Password reset emails are not arriving after four attempts. Customer is locked out."], "needs_review"],
  ["SF-1032", 190, 10, "email", "Webhook deliveries delayed", "Webhook deliveries to our endpoint have been delayed by about 20 minutes since yesterday. Not blocking us, but noticeable.",
    ["bug", "P2", "neutral", 0.84, "Webhook deliveries are delayed by about 20 minutes since yesterday. Not blocking."], "in_progress"],
  ["SF-1031", 240, 11, "email", "Why did our bill go up?", "Why did our bill go up from $49 to $79? Nobody told us about any price change.",
    ["billing", "P2", "frustrated", 0.83, "Customer's bill rose from $49 to $79 without notice; asks why."], "needs_review"],
  ["SF-1030", 300, 1, "email", "Blank PDFs going to our clients", "You pushed an update and now ALL our scheduled reports are emailing blank PDFs to our clients. This is embarrassing and we're losing clients over it. Fix it NOW.",
    ["bug", "P1", "angry", 0.95, "Since the latest update, all scheduled reports email blank PDFs to the customer's clients. Customer is losing clients."], "escalated"],
  ["SF-1029", 360, 7, "web_form", "Date picker ignores week start", "Small thing: the date picker shows Sunday as the first day of the week even though I set Monday in my preferences.",
    ["bug", "P3", "neutral", 0.87, "Date picker starts weeks on Sunday despite a Monday preference."], "resolved"],
  ["SF-1028", 420, 8, "email", "Okta SSO support?", "Is there any plan to support SSO with Okta? Our IT team is asking before we roll this out to 200 people.",
    ["feature_request", "P3", "neutral", 0.81, "IT team asks whether Okta SSO is supported before a 200-seat rollout."], "needs_review"],
  ["SF-1027", 510, 12, "chat", "Search breaks on apostrophes", "Search returns no results for any query containing an apostrophe, e.g. O'Brien. We tried wrapping it in quotes and escaping it with a backslash, same result.",
    ["bug", "P2", "frustrated", 0.88, "Search returns nothing for queries with an apostrophe (e.g. O'Brien). Quoting and escaping did not help."], "escalated"],
  ["SF-1026", 600, 3, "email", "Extra seats bought by mistake", "We accidentally bought 5 extra seats. Can we get a refund for those, or just downgrade?",
    ["billing", "P2", "neutral", 0.9, "Customer bought five seats by mistake and asks for a refund or a downgrade."], "needs_review"],
  ["SF-1025", 700, 2, "web_form", "Dark mode", "Honestly it's frustrating that there's still no dark mode. Every other tool we use has it.",
    ["feature_request", "P3", "frustrated", 0.85, "Customer is frustrated that dark mode is still missing."], "resolved"],
  ["SF-1024", 820, 6, "email", "Android app crashes on launch", "The mobile app crashes immediately on launch on Android 15 since today's update. We reinstalled, cleared the cache and rebooted, still crashes. Our field team can't log any visits.",
    ["bug", "P1", "frustrated", 0.9, "Android app crashes on launch on Android 15 after today's update. Field team is blocked."], "needs_review"],
  ["SF-1023", 950, 9, "chat", "Add a view-only teammate", "How do I add a new team member with view-only access?",
    ["account", "P3", "neutral", 0.86, "Customer asks how to add a teammate with view-only access."], "resolved"],
  ["SF-1022", 1100, 10, "email", "DPA before renewal", "Our legal team needs a copy of your DPA and the current sub-processor list before we can sign the renewal.",
    ["account", "P2", "neutral", 0.74, "Customer's legal team needs the DPA and sub-processor list before renewal."], "needs_review"],
  ["SF-1021", 1300, 4, "web_form", "Payment methods", "Which payment methods do you accept besides credit card?",
    ["billing", "P3", "neutral", 0.91, "Customer asks which payment methods are accepted besides credit card."], "resolved"],
  ["SF-1020", 1500, 14, "email", "(no subject)", "it's not working",
    ["other", "P2", "neutral", 0.28, "Insufficient information to classify. Recommend manual review."], "needs_review"],
  ["SF-1019", 1700, 11, "email", "Timestamps in UTC", "The 'Last updated' timestamp on reports shows UTC instead of our account timezone (IST).",
    ["bug", "P3", "neutral", 0.78, "Report timestamps show UTC instead of the account timezone."], "in_progress"],
  ["SF-1018", 1900, 8, "email", "Partner programme for agencies", "Do you have a partner or reseller program for agencies?",
    ["other", "P3", "neutral", 0.64, "Agency asks about a partner or reseller programme."], "needs_review"],
  ["SF-1017", 2200, 12, "email", "Bulk tag API", "Would love an API endpoint to bulk-update tags on records. Happy to beta test it!",
    ["feature_request", "P3", "positive", 0.88, "Customer requests a bulk tag-update API endpoint and offers to beta test."], "resolved"],
  // New tickets: not analysed yet; "Run AI analysis" fills them in (mock in step 1, real LLM from step 2).
  ["SF-1043", 2, 3, "chat", "Seats not updating after upgrade", "We upgraded to Business an hour ago but the seat count still shows 10 and new invites fail.", null, "new"],
  ["SF-1044", 1, 7, "email", "Can't connect Slack integration", "Clicking 'Connect Slack' shows a blank popup and nothing happens. Tried Chrome and Firefox.", null, "new"],
];

/** Analyses that the mock "Run AI analysis" returns for new tickets. */
export const PENDING_ANALYSES: Record<string, A> = {
  "SF-1043": ["billing", "P2", "frustrated", 0.82, "After upgrading to Business, the seat count still shows 10 and new invites fail."],
  "SF-1044": ["bug", "P2", "neutral", 0.87, "The Slack integration popup is blank in Chrome and Firefox, so Slack cannot be connected."],
};

const KNOWLEDGE: Omit<KnowledgeDoc, "resolvedAt">[] = [
  { id: "KB-101", category: "billing", subject: "Double charge on card", body: "We were charged twice for the monthly subscription.", resolution: "Confirmed a duplicate charge caused by a payment-gateway retry. Refunded the second charge (5-7 business days) and sent the refund receipt." },
  { id: "KB-102", category: "billing", subject: "Invoice needs VAT ID", body: "Our invoice is missing our VAT number.", resolution: "Added the VAT ID under Settings > Billing > Tax details, regenerated the invoice and emailed the PDF. Future invoices include it automatically." },
  { id: "KB-103", category: "billing", subject: "Price increased without notice", body: "Our plan price went up this month.", resolution: "Explained the legacy-plan migration announced by email 60 days earlier and applied a one-month courtesy credit for the difference." },
  { id: "KB-104", category: "billing", subject: "Bought too many seats", body: "We purchased seats we don't need.", resolution: "Removed the unused seats; the unused portion was credited to the account balance (prorated) rather than refunded to card." },
  { id: "KB-105", category: "billing", subject: "Seat count not updated after upgrade", body: "Upgraded plan but seats still show the old number.", resolution: "Plan changes sync within 5 minutes; a stuck sync was re-triggered from the billing admin and invites started working." },
  { id: "KB-106", category: "billing", subject: "Pay by bank transfer", body: "Can we pay by bank transfer instead of card?", resolution: "Bank transfer and invoicing are available on annual Business plans; card and PayPal on all plans." },
  { id: "KB-201", category: "account", subject: "Password reset email not received", body: "Reset emails never arrive.", resolution: "The customer's mail server rejected our sender. Asked them to allowlist our mail domain, then sent a manual reset link valid for 30 minutes." },
  { id: "KB-202", category: "account", subject: "Add read-only teammate", body: "How to give someone view-only access?", resolution: "Settings > Team > Invite, choose the 'Viewer' role. Viewers can open dashboards and reports but cannot edit or export." },
  { id: "KB-203", category: "account", subject: "Suspicious API keys and logins", body: "API keys we did not create appeared on our account.", resolution: "Revoked all API keys, forced logout of all sessions, required a password reset and enforced 2FA. Security reviewed audit logs within 24h." },
  { id: "KB-204", category: "account", subject: "Request for DPA and sub-processors", body: "Legal needs our data processing agreement.", resolution: "Shared the signed DPA template and the sub-processor list from the trust center; countersigned within 3 business days." },
  { id: "KB-301", category: "bug", subject: "Dashboard returning 500 errors", body: "All dashboards show server error 500.", resolution: "Linked to the incident on the status page (database failover). Resolved in 47 minutes; the customer received the incident report." },
  { id: "KB-302", category: "bug", subject: "CSV import date error on large file", body: "Import fails with invalid date format on big files.", resolution: "Chunked imports lost the header row after 1,000 rows. Fixed in 4.12; workaround was importing files under 1,000 rows." },
  { id: "KB-303", category: "bug", subject: "Webhooks arriving late", body: "Webhook events delayed by many minutes.", resolution: "Queue backlog after a deploy; workers were scaled and delays returned to under 5 seconds. Failed deliveries replayed automatically." },
  { id: "KB-304", category: "bug", subject: "Scheduled report PDFs are blank", body: "Scheduled emails contain empty PDFs.", resolution: "PDF renderer regression; engineering rolled back the renderer and re-sent the affected reports." },
  { id: "KB-305", category: "bug", subject: "Search fails with special characters", body: "Searching for names with an apostrophe returns nothing.", resolution: "The query parser didn't escape apostrophes; fixed in 4.9. Workaround: search for the part after the apostrophe." },
  { id: "KB-306", category: "bug", subject: "Mobile app crash after update", body: "Android app closes on launch after update.", resolution: "Crash in the push-notification SDK on some Android versions. Hotfix 3.8.1 shipped the same day via the Play Store." },
  { id: "KB-307", category: "bug", subject: "Slack connect popup blank", body: "OAuth popup for Slack is empty.", resolution: "Third-party cookie blocking broke the OAuth popup; switched to a redirect flow in 4.11. Workaround: allow third-party cookies for our domain." },
  { id: "KB-401", category: "feature_request", subject: "Okta SSO support", body: "Do you support SAML SSO with Okta?", resolution: "SAML SSO (Okta, Azure AD, Google) is available on Business and above. Shared the setup guide." },
  { id: "KB-402", category: "feature_request", subject: "Dark mode request", body: "Please add a dark theme.", resolution: "Logged the vote on the public roadmap item 'Dark mode' (planned for Q1). Customer subscribed to updates." },
  { id: "KB-403", category: "feature_request", subject: "Schedule exports to cloud storage", body: "Can exports be scheduled to Google Drive?", resolution: "Not native yet; logged on the roadmap. Workaround: scheduled export email plus the Zapier integration into Google Drive." },
  { id: "KB-501", category: "other", subject: "Agency partner program", body: "Do you work with agencies or resellers?", resolution: "Shared the partner programme page (20% recurring commission) and connected them with the partnerships team." },
];

const ago = (now: number, mins: number) => new Date(now - mins * 60_000).toISOString();

export function buildAnalysis(text: string, a: A, at: string, latencyMs: number): Analysis {
  const [category, priority, sentiment, confidence, summary] = a;
  return { category, priority, sentiment, confidence, summary, model: MOCK_MODEL, analyzedAt: at, latencyMs,
    flags: computeFlags(text, { confidence, priority, sentiment }) };
}

export function seedWorkspace(now = Date.now()): Workspace {
  const tickets: Ticket[] = ROWS.map(([id, mins, c, channel, subject, body, a, status]) => {
    const createdAt = ago(now, mins);
    const analysis = a ? buildAnalysis(`${subject} ${body}`, a, ago(now, Math.max(mins - 1, 0)), 900 + (mins % 7) * 210) : null;
    const decided = status === "in_progress" || status === "resolved" || status === "escalated" || status === "awaiting_approval";
    return {
      id, subject, body, channel, createdAt, status, customer: CUSTOMERS[c],
      assignee: decided ? "Alex Rivera" : null, analysis,
      decision: decided && analysis
        ? { status: "accepted", category: analysis.category, priority: analysis.priority, decidedBy: "Alex Rivera", decidedAt: ago(now, Math.max(mins - 3, 0)) }
        : { status: "pending" },
    };
  });

  const knowledge = KNOWLEDGE.map((k, i) => ({ ...k, resolvedAt: ago(now, 60 * 24 * (20 + i * 3)) }));

  const draftBody = "Hi Ahmed,\n\nThanks for flagging this. I've added your VAT number under Settings > Billing > Tax details and regenerated the October invoice, which is attached. All future invoices will include it automatically.\n\nBest,\n[Agent name]";
  const drafts: Draft[] = [{
    id: "DR-1", ticketId: "SF-1034", body: draftBody, originalBody: draftBody, status: "generated", model: MOCK_MODEL,
    sources: [{ id: "KB-102", similarity: 0.71 }, { id: "KB-106", similarity: 0.18 }, { id: "KB-101", similarity: 0.12 }],
    generatedAt: ago(now, 120),
  }];

  const escalations: Escalation[] = [
    { id: "ESC-7", ticketId: "SF-1030", channel: "#eng-escalations", status: "pending_approval", requestedBy: "Alex Rivera", requestedAt: ago(now, 280), slackMode: "simulated",
      brief: { summary: "Scheduled reports email blank PDFs to Contoso's clients since the latest release.\nCustomer reports losing clients; all scheduled reports affected.",
        troubleshooting: ["Confirmed affected: all scheduled reports for the workspace", "Customer has not changed report templates", "Matches past incident KB-304 (PDF renderer regression)"],
        priority: "P1", ticketUrl: "https://supportflow.example/tickets/SF-1030", impact: "Business plan · client-facing reports" } },
    { id: "ESC-6", ticketId: "SF-1027", channel: "#eng-escalations", status: "posted", requestedBy: "Alex Rivera", requestedAt: ago(now, 480), decidedBy: "Jordan Lee", decidedAt: ago(now, 470), slackMode: "simulated", slackMessageTs: "sim-1717",
      brief: { summary: "Search returns no results for queries containing an apostrophe.\nAffects customer-name searches such as O'Brien.",
        troubleshooting: ["Wrapping the term in quotes: same result", "Escaping with a backslash: same result"],
        priority: "P2", ticketUrl: "https://supportflow.example/tickets/SF-1027", impact: "Pro plan · search unusable for some names" } },
  ];

  return {
    tickets, knowledge, drafts, escalations, currentAgent: "Alex Rivera", currentRole: "agent",
    audit: tickets.filter((t) => t.analysis).flatMap((t, i) => [
      { id: `AU-${i}-a`, ticketId: t.id, at: t.analysis!.analyzedAt, actor: "ai" as const, action: "Classified ticket", detail: `${t.analysis!.category} · ${t.analysis!.priority} · confidence ${t.analysis!.confidence.toFixed(2)}` },
      ...(t.decision.status !== "pending" ? [{ id: `AU-${i}-d`, ticketId: t.id, at: t.decision.decidedAt!, actor: "agent" as const, action: "Accepted classification", detail: t.decision.decidedBy }] : []),
    ]),
  };
}
