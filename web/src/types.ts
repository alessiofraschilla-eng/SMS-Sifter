export const TIERS = ["HOT", "WARM", "COLD", "DEAD", "DNC"] as const;
export type Tier = (typeof TIERS)[number];

export const STATUSES = [
  "new", "contacted", "appointment", "offer_made", "under_contract", "closed", "dead",
] as const;
export type Status = (typeof STATUSES)[number];

export const STATUS_LABEL: Record<Status, string> = {
  new: "New",
  contacted: "Contacted",
  appointment: "Appointment",
  offer_made: "Offer made",
  under_contract: "Under contract",
  closed: "Closed",
  dead: "Dead",
};

export interface Lead {
  id: string;
  phone: string;
  name: string | null;
  property_address: string | null;
  tier: Tier;
  score: number;
  last_reply: string | null;
  last_reply_at: string | null;
  reply_count: number;
  tier_override: Tier | null;
  status: Status;
  assigned_to: string | null;
  asking_price: number | null;
  deleted_at: string | null;
  effective_tier: Tier;
  effective_score: number;
  created_at: string;
}

export type LeadPatch = Partial<
  Pick<Lead, "name" | "property_address" | "tier_override" | "status" | "assigned_to" | "asking_price" | "deleted_at">
>;

export interface Message {
  id: string;
  lead_id: string;
  direction: "in" | "out";
  body: string;
  sent_at: string;
  score: number | null;
  tier: Tier | null;
  reasons: string[];
  grader: string | null;
}

export interface Note {
  id: string;
  lead_id: string;
  author_email: string;
  body: string;
  created_at: string;
}

export interface TeamMember {
  email: string;
  name: string;
}
