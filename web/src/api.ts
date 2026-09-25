// Data layer. Talks to Supabase, or to in-memory sample data when VITE_DEMO=1
// (or no Supabase URL is configured) so the dashboard can be previewed.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Lead, LeadPatch, Message, Note, TeamMember } from "./types";
import { demoData } from "./demo";

export interface Api {
  demo: boolean;
  currentEmail(): Promise<string | null>;
  onAuthChange(cb: (email: string | null) => void): () => void;
  sendLoginLink(email: string): Promise<void>;
  signOut(): Promise<void>;
  team(): Promise<TeamMember[]>;
  leads(): Promise<Lead[]>;
  thread(leadId: string): Promise<{ messages: Message[]; notes: Note[] }>;
  updateLead(id: string, patch: LeadPatch): Promise<void>;
  addNote(leadId: string, body: string): Promise<void>;
  deleteNote(id: string): Promise<void>;
  subscribe(onChange: () => void): () => void;
}

function check<T>(res: { data: T | null; error: { message: string } | null }): T {
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

function supabaseApi(sb: SupabaseClient): Api {
  return {
    demo: false,
    async currentEmail() {
      const { data } = await sb.auth.getSession();
      return data.session?.user.email ?? null;
    },
    onAuthChange(cb) {
      const { data } = sb.auth.onAuthStateChange((_e, session) => cb(session?.user.email ?? null));
      return () => data.subscription.unsubscribe();
    },
    async sendLoginLink(email) {
      // shouldCreateUser: false -> only accounts you invited can get a link.
      const { error } = await sb.auth.signInWithOtp({
        email,
        options: { shouldCreateUser: false, emailRedirectTo: window.location.origin },
      });
      if (error) throw new Error(error.message);
    },
    async signOut() {
      await sb.auth.signOut();
    },
    async team() {
      return check(await sb.from("team_members").select("email,name").order("name"));
    },
    async leads() {
      return check(await sb.from("ranked_leads").select("*"));
    },
    async thread(leadId) {
      const [m, n] = await Promise.all([
        sb.from("messages").select("*").eq("lead_id", leadId).order("sent_at"),
        sb.from("notes").select("*").eq("lead_id", leadId).order("created_at"),
      ]);
      return { messages: check(m), notes: check(n) };
    },
    async updateLead(id, patch) {
      check(await sb.from("leads").update(patch).eq("id", id));
    },
    async addNote(leadId, body) {
      check(await sb.from("notes").insert({ lead_id: leadId, body }));
    },
    async deleteNote(id) {
      check(await sb.from("notes").delete().eq("id", id));
    },
    subscribe(onChange) {
      const channel = sb
        .channel("sifter")
        .on("postgres_changes", { event: "*", schema: "public", table: "leads" }, onChange)
        .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, onChange)
        .on("postgres_changes", { event: "*", schema: "public", table: "notes" }, onChange)
        .subscribe();
      return () => void sb.removeChannel(channel);
    },
  };
}

const TIER_RANK = { HOT: 0, WARM: 1, COLD: 2, DEAD: 3, DNC: 4 } as const;

function rank(leads: Lead[]): Lead[] {
  for (const l of leads) {
    l.effective_tier = l.tier_override ?? l.tier;
    l.effective_score = l.effective_tier === "DNC" ? 0 : l.score;
  }
  return [...leads].sort(
    (a, b) =>
      TIER_RANK[a.effective_tier] - TIER_RANK[b.effective_tier] ||
      b.score - a.score ||
      (b.last_reply_at ?? "").localeCompare(a.last_reply_at ?? ""),
  );
}

function demoApi(): Api {
  const me = "alessio@example.com";
  const data = demoData();
  const listeners = new Set<() => void>();
  const changed = () => listeners.forEach((f) => f());
  let email: string | null = me;
  return {
    demo: true,
    async currentEmail() {
      return email;
    },
    onAuthChange() {
      return () => {};
    },
    async sendLoginLink() {},
    async signOut() {
      email = null;
      location.reload();
    },
    async team() {
      return data.team;
    },
    async leads() {
      return rank(data.leads.map((l) => ({ ...l })));
    },
    async thread(leadId) {
      return {
        messages: data.messages.filter((m) => m.lead_id === leadId),
        notes: data.notes.filter((n) => n.lead_id === leadId),
      };
    },
    async updateLead(id, patch) {
      Object.assign(data.leads.find((l) => l.id === id)!, patch);
      changed();
    },
    async addNote(leadId, body) {
      data.notes.push({ id: crypto.randomUUID(), lead_id: leadId, author_email: me, body, created_at: new Date().toISOString() });
      changed();
    },
    async deleteNote(id) {
      data.notes = data.notes.filter((n) => n.id !== id);
      changed();
    },
    subscribe(onChange) {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
  };
}

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
const wantDemo = import.meta.env.VITE_DEMO === "1" || !url || !key;

export const api: Api = wantDemo ? demoApi() : supabaseApi(createClient(url!, key!));
