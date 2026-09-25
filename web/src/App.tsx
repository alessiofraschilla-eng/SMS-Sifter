import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import {
  STATUSES, STATUS_LABEL, TIERS,
  type Lead, type LeadPatch, type Message, type Note, type TeamMember, type Tier,
} from "./types";

type Filter = "ACTIVE" | Tier | "ALL";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "ACTIVE", label: "Active" },
  { key: "HOT", label: "Hot" },
  { key: "WARM", label: "Warm" },
  { key: "COLD", label: "Cold" },
  { key: "DEAD", label: "Dead" },
  { key: "DNC", label: "DNC" },
  { key: "ALL", label: "All" },
];

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  if (m < 60 * 24) return `${Math.round(m / 60)}h`;
  return `${Math.round(m / 1440)}d`;
}

function fmtPhone(p: string): string {
  const d = p.replace(/\D/g, "").slice(-10);
  return d.length === 10 ? `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}` : p;
}

function TierBadge({ tier }: { tier: Tier }) {
  return <span className={`tier tier-${tier.toLowerCase()}`}>{tier}</span>;
}

function ScoreBar({ score, tier }: { score: number; tier: Tier }) {
  return (
    <span className="score" title={`Score ${score}`}>
      <span className="score-num">{score}</span>
      <span className="score-track">
        <span className={`score-fill fill-${tier.toLowerCase()}`} style={{ width: `${score}%` }} />
      </span>
    </span>
  );
}

// ---------- Login ----------

function Login() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");
  return (
    <div className="login">
      <form
        className="login-card"
        onSubmit={async (e) => {
          e.preventDefault();
          setState("sending");
          try {
            await api.sendLoginLink(email.trim().toLowerCase());
            setState("sent");
          } catch (err) {
            setError((err as Error).message);
            setState("error");
          }
        }}
      >
        <div className="brand brand-lg"><span className="brand-mark" />SMS Sifter</div>
        <p className="muted">Private lead desk. Invited members only.</p>
        {state === "sent" ? (
          <p className="login-sent">Check {email} for a sign-in link.</p>
        ) : (
          <>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            <button className="btn btn-primary" disabled={state === "sending"}>
              {state === "sending" ? "Sending…" : "Email me a sign-in link"}
            </button>
            {state === "error" && <p className="error">{error}</p>}
          </>
        )}
      </form>
    </div>
  );
}

// ---------- Lead detail ----------

function EditableText({ value, placeholder, onSave, className }: {
  value: string | null; placeholder: string; onSave: (v: string | null) => void; className?: string;
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  return (
    <input
      className={`inline-edit ${className ?? ""}`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft.trim() !== (value ?? "") && onSave(draft.trim() || null)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

function LeadDetail({ lead, team, me, onPatch, onClose, version }: {
  lead: Lead; team: TeamMember[]; me: string; version: number;
  onPatch: (p: LeadPatch) => void; onClose: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [noteDraft, setNoteDraft] = useState("");
  const nameOf = (email: string) => team.find((t) => t.email === email)?.name ?? email;

  useEffect(() => {
    let live = true;
    api.thread(lead.id).then((t) => {
      if (live) {
        setMessages(t.messages);
        setNotes(t.notes);
      }
    });
    return () => {
      live = false;
    };
  }, [lead.id, version]);

  const latestIn = [...messages].reverse().find((m) => m.direction === "in" && m.tier);

  return (
    <aside className="detail" aria-label="Lead detail">
      <div className="detail-head">
        <button className="btn btn-ghost back" onClick={onClose} aria-label="Back to list">←</button>
        <div className="detail-title">
          <EditableText className="name-edit" value={lead.name} placeholder="Add name" onSave={(v) => onPatch({ name: v })} />
          <a className="phone mono" href={`tel:${lead.phone}`}>{fmtPhone(lead.phone)}</a>
        </div>
        <div className="detail-grade">
          <TierBadge tier={lead.effective_tier} />
          <span className="big-score mono">{lead.effective_score}</span>
        </div>
      </div>

      <div className="fields">
        <label>Property
          <EditableText value={lead.property_address} placeholder="Add address" onSave={(v) => onPatch({ property_address: v })} />
        </label>
        <label>Status
          <select value={lead.status} onChange={(e) => onPatch({ status: e.target.value as Lead["status"] })}>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </label>
        <label>Owner
          <select value={lead.assigned_to ?? ""} onChange={(e) => onPatch({ assigned_to: e.target.value || null })}>
            <option value="">Unassigned</option>
            {team.map((t) => <option key={t.email} value={t.email}>{t.name}{t.email === me ? " (me)" : ""}</option>)}
          </select>
        </label>
        <label>Tier
          <select
            value={lead.tier_override ?? ""}
            onChange={(e) => onPatch({ tier_override: (e.target.value || null) as Tier | null })}
          >
            <option value="">Auto ({lead.tier})</option>
            {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>Asking price
          <EditableText
            value={lead.asking_price == null ? null : String(lead.asking_price)}
            placeholder="$"
            onSave={(v) => {
              const n = v == null ? null : Number(v.replace(/[$,\s]/g, ""));
              onPatch({ asking_price: n == null || Number.isNaN(n) ? null : n });
            }}
          />
        </label>
      </div>

      {latestIn && latestIn.reasons.length > 0 && (
        <p className="why"><span className="muted">Why {latestIn.tier}:</span> {latestIn.reasons.join(" · ")}</p>
      )}

      <h3 className="section-h">Conversation</h3>
      <ol className="convo">
        {messages.map((m) => (
          <li key={m.id} className={`bubble ${m.direction}`}>
            <p>{m.body}</p>
            <span className="meta">
              {m.tier && <TierBadge tier={m.tier} />}
              {m.score != null && <span className="mono">{m.score}</span>}
              <time dateTime={m.sent_at} title={new Date(m.sent_at).toLocaleString()}>{timeAgo(m.sent_at)}</time>
            </span>
          </li>
        ))}
      </ol>

      <h3 className="section-h">Notes</h3>
      <ul className="notes">
        {notes.map((n) => (
          <li key={n.id}>
            <div className="note-meta">
              <strong>{nameOf(n.author_email)}</strong>
              <time className="muted" dateTime={n.created_at}>{timeAgo(n.created_at)}</time>
              {n.author_email === me && (
                <button className="link-btn" onClick={() => api.deleteNote(n.id).then(() => setNotes(notes.filter((x) => x.id !== n.id)))}>
                  delete
                </button>
              )}
            </div>
            <p>{n.body}</p>
          </li>
        ))}
        {notes.length === 0 && <li className="muted empty-note">No notes yet.</li>}
      </ul>
      <form
        className="note-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!noteDraft.trim()) return;
          await api.addNote(lead.id, noteDraft.trim());
          setNoteDraft("");
          setNotes((await api.thread(lead.id)).notes);
        }}
      >
        <textarea
          placeholder="Add a note (call outcome, condition, numbers)…"
          value={noteDraft}
          onChange={(e) => setNoteDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) (e.currentTarget.form as HTMLFormElement).requestSubmit();
          }}
        />
        <button className="btn btn-primary" disabled={!noteDraft.trim()}>Add note</button>
      </form>
    </aside>
  );
}

// ---------- Main desk ----------

function Desk({ me }: { me: string }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [filter, setFilter] = useState<Filter>("ACTIVE");
  const [mine, setMine] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [l, t] = await Promise.all([api.leads(), api.team()]);
      setLeads(l);
      setTeam(t);
      setVersion((v) => v + 1);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    return api.subscribe(load);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<Tier, number> = { HOT: 0, WARM: 0, COLD: 0, DEAD: 0, DNC: 0 };
    leads.forEach((l) => c[l.effective_tier]++);
    return c;
  }, [leads]);
  const today = useMemo(
    () => leads.filter((l) => l.last_reply_at && Date.now() - new Date(l.last_reply_at).getTime() < 86_400_000).length,
    [leads],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const qDigits = q.replace(/\D/g, "");
    return leads.filter((l) => {
      if (filter === "ACTIVE" && (l.effective_tier === "DNC" || l.effective_tier === "DEAD" || l.status === "dead" || l.status === "closed")) return false;
      if (filter !== "ACTIVE" && filter !== "ALL" && l.effective_tier !== filter) return false;
      if (mine && l.assigned_to !== me) return false;
      if (!q) return true;
      return (
        (qDigits.length >= 3 && l.phone.includes(qDigits)) ||
        [l.name, l.property_address, l.last_reply].some((s) => s?.toLowerCase().includes(q))
      );
    });
  }, [leads, filter, mine, query, me]);

  const current = leads.find((l) => l.id === selected) ?? null;

  // Keyboard: j/k to move, / to search, Esc to close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") (e.target as HTMLElement).blur();
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape") {
        setSelected(null);
      } else if (e.key === "j" || e.key === "k") {
        const i = visible.findIndex((l) => l.id === selected);
        const next = e.key === "j" ? Math.min(visible.length - 1, i + 1) : Math.max(0, i - 1);
        if (visible[next]) setSelected(visible[next].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selected]);

  const patch = async (id: string, p: LeadPatch) => {
    setLeads((ls) => ls.map((l) => (l.id === id ? { ...l, ...p } : l)));
    try {
      await api.updateLead(id, p);
    } catch (err) {
      setError((err as Error).message);
    }
    load();
  };

  const nameOf = (email: string | null) => (email ? team.find((t) => t.email === email)?.name ?? email : "");

  return (
    <div className={`app ${current ? "has-detail" : ""}`}>
      <header className="topbar">
        <div className="brand"><span className="brand-mark" />SMS Sifter{api.demo && <span className="demo-pill">demo</span>}</div>
        <div className="stats" role="list">
          {TIERS.map((t) => (
            <button key={t} role="listitem" className={`stat stat-${t.toLowerCase()} ${filter === t ? "on" : ""}`} onClick={() => setFilter(filter === t ? "ACTIVE" : t)}>
              <span className="stat-n mono">{counts[t]}</span>
              <span className="stat-l">{t}</span>
            </button>
          ))}
          <div className="stat stat-today">
            <span className="stat-n mono">{today}</span>
            <span className="stat-l">replies 24h</span>
          </div>
        </div>
        <div className="who">
          <span className="muted">{nameOf(me) || me}</span>
          <button className="btn btn-ghost" onClick={() => api.signOut()}>Sign out</button>
        </div>
      </header>

      <main className="list-pane">
        <div className="toolbar">
          <div className="tabs" role="tablist">
            {FILTERS.map((f) => (
              <button key={f.key} role="tab" aria-selected={filter === f.key} className={`tab ${filter === f.key ? "on" : ""}`} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <label className="mine">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine
          </label>
          <input
            ref={searchRef}
            className="search"
            type="search"
            placeholder="Search name, phone, address, reply   /"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {error && <p className="error banner">{error}</p>}
        {!api.demo && version > 0 && !team.some((t) => t.email === me) && (
          <p className="error banner">{me} is not on the team list, so no leads are shown. Ask the owner to add you.</p>
        )}
        <table className="leads">
          <thead>
            <tr>
              <th className="c-rank">#</th>
              <th className="c-tier">Tier</th>
              <th className="c-score">Score</th>
              <th>Lead</th>
              <th className="c-reply">Last reply</th>
              <th className="c-status">Status</th>
              <th className="c-owner">Owner</th>
              <th className="c-when">When</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((l, i) => (
              <tr key={l.id} className={l.id === selected ? "sel" : ""} onClick={() => setSelected(l.id)} tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && setSelected(l.id)}>
                <td className="c-rank mono muted">{i + 1}</td>
                <td className="c-tier"><TierBadge tier={l.effective_tier} /></td>
                <td className="c-score"><ScoreBar score={l.effective_score} tier={l.effective_tier} /></td>
                <td className="c-lead">
                  <div className="lead-name">{l.name ?? fmtPhone(l.phone)}</div>
                  <div className="lead-sub muted">{l.name ? fmtPhone(l.phone) : l.property_address ?? ""}{l.name && l.property_address ? ` · ${l.property_address}` : ""}</div>
                  <div className="lead-reply-m muted">{l.last_reply}</div>
                </td>
                <td className="c-reply"><span className="reply">{l.last_reply}</span></td>
                <td className="c-status"><span className={`status st-${l.status}`}>{STATUS_LABEL[l.status]}</span></td>
                <td className="c-owner muted">{nameOf(l.assigned_to)}</td>
                <td className="c-when mono muted">{timeAgo(l.last_reply_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && <p className="empty muted">No leads here yet.</p>}
        <p className="hint muted">j / k to move · / to search · Esc to close</p>
      </main>

      {current && (
        <LeadDetail
          key={current.id}
          lead={current}
          team={team}
          me={me}
          version={version}
          onPatch={(p) => patch(current.id, p)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

export default function App() {
  const [email, setEmail] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    api.currentEmail().then(setEmail);
    return api.onAuthChange(setEmail);
  }, []);
  if (email === undefined) return null;
  return email ? <Desk me={email.toLowerCase()} /> : <Login />;
}
