// Sample data for preview mode. Phone numbers use the fictional 555-01xx range.
import type { Lead, Message, Note, Status, TeamMember, Tier } from "./types";

type Row = [phone: string, name: string | null, address: string | null, status: Status,
  assigned: string | null, replies: [minutesAgo: number, body: string, tier: Tier, score: number, reasons: string[]][]];

const A = "alessio@example.com";
const P = "partner@example.com";

const ROWS: Row[] = [
  ["+15550100105", "Linda Morales", "412 Oak Hollow Dr", "appointment", A, [
    [190, "Who is this?", "COLD", 45, ["curious who we are", "asked a question"]],
    [12, "Yes please call me, I inherited the place and want to sell it fast", "HOT", 100, ["affirmative", "wants to sell", "wants a call/visit", "urgency", "motivation signal"]],
  ]],
  ["+15550100144", null, "88 Pine St", "new", null, [
    [34, "Yes I'm thinking about selling, what would you offer for it? Roof needs repairs", "HOT", 100, ["affirmative", "wants to sell", "asking for an offer", "motivation signal"]],
  ]],
  ["+15550100103", "Gary Chen", null, "contacted", P, [
    [600, "Maybe, depends on the price", "WARM", 60, ["asking about price", "maybe"]],
    [95, "Actually yes, can we talk tomorrow?", "HOT", 90, ["affirmative", "wants a call/visit", "asked a question"]],
  ]],
  ["+15550100112", null, null, "new", null, [[55, "Sure, make me an offer", "HOT", 90, ["affirmative", "asking for an offer"]]]],
  ["+15550100110", "Tom Reyes", "1520 W 3rd Ave", "offer_made", A, [[1500, "How much would you pay?", "HOT", 90, ["asking for an offer", "asking about price", "asked a question"]]]],
  ["+15550100106", null, null, "new", null, [[240, "I'd like to learn more", "HOT", 75, ["wants more info"]]]],
  ["+15550100108", null, null, "new", null, [[2900, "Not right now but maybe next year", "WARM", 50, ["maybe", "timing is later"]]]],
  ["+15550100104", null, null, "new", null, [[3100, "Who is this?", "COLD", 45, ["curious who we are", "asked a question"]]]],
  ["+15550100111", null, null, "dead", null, [[4000, "no", "DEAD", 0, ["flat no"]]]],
  ["+15550100101", null, null, "dead", null, [[4300, "Not interested", "DEAD", 0, ["declined"]]]],
  ["+15550100109", null, null, "dead", null, [[5000, "stop texting me you vultures", "DNC", 0, ["opt-out / wrong number"]]]],
  ["+15550100107", null, null, "dead", null, [[5200, "wrong number", "DNC", 0, ["opt-out / wrong number"]]]],
  ["+15550100102", null, null, "dead", null, [[5400, "STOP", "DNC", 0, ["opt-out / wrong number"]]]],
];

export function demoData() {
  const now = Date.now();
  const ago = (m: number) => new Date(now - m * 60_000).toISOString();
  const team: TeamMember[] = [
    { email: A, name: "Alessio" },
    { email: P, name: "Partner" },
  ];
  const leads: Lead[] = [];
  const messages: Message[] = [];
  const notes: Note[] = [];
  ROWS.forEach(([phone, name, address, status, assigned, replies], i) => {
    const id = `lead-${i}`;
    const last = replies[replies.length - 1];
    const dnc = replies.some((r) => r[2] === "DNC");
    leads.push({
      id, phone, name, property_address: address, status, assigned_to: assigned,
      tier: dnc ? "DNC" : last[2], score: dnc ? 0 : last[3],
      last_reply: last[1], last_reply_at: ago(last[0]), reply_count: replies.length,
      tier_override: null, asking_price: null,
      effective_tier: last[2], effective_score: last[3], created_at: ago(replies[0][0] + 60),
    });
    messages.push({
      id: `${id}-out`, lead_id: id, direction: "out", sent_at: ago(replies[0][0] + 45),
      body: "Hi, this is Alessio. Would you consider an offer on your property?",
      score: null, tier: null, reasons: [], grader: null,
    });
    replies.forEach(([m, body, tier, score, reasons], j) =>
      messages.push({ id: `${id}-${j}`, lead_id: id, direction: "in", body, sent_at: ago(m), score, tier, reasons, grader: "rules" }),
    );
  });
  notes.push(
    { id: "n1", lead_id: "lead-0", author_email: A, body: "Called her back. Inherited from her mom, house is vacant. Walkthrough Saturday 10am.", created_at: ago(8) },
    { id: "n2", lead_id: "lead-4", author_email: A, body: "Sent $142k cash offer, 14-day close.", created_at: ago(1400) },
    { id: "n3", lead_id: "lead-4", author_email: P, body: "Comps came in around $210k ARV, needs ~$35k rehab. Offer is solid.", created_at: ago(1380) },
  );
  return { team, leads, messages, notes };
}
