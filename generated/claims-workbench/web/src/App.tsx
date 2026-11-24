// Generic renderer for a generated app: every screen, control, rule binding and action
// comes from app.g.ts. Business logic is never evaluated here; the browser sends control
// values to the API and renders what the generated .NET rules return.
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import { app } from "./app.g";
import type { ActionDef, ControlDef, DemoUser, Evaluation, Json, Row } from "./types";

/** Power Fx property each input widget exposes to formulas. */
const INPUT_PROP: Record<string, string> = {
  text: "Text",
  date: "SelectedDate",
  select: "Selected.Value",
  checkbox: "Value",
};

const isInput = (c: ControlDef): boolean => c.widget in INPUT_PROP;
const keyOf = (c: ControlDef): string => `${c.name}.${INPUT_PROP[c.widget] ?? "Text"}`;

function show(v: Json | undefined): string {
  if (v === undefined || v === null || v === "") return "(blank)";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

export function App() {
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [user, setUser] = useState<string>("");
  const [screen, setScreen] = useState<string>(app.screens[0]?.screen ?? "");
  const [inputs, setInputs] = useState<Record<string, Json>>({});
  const [ev, setEv] = useState<Evaluation>({ values: {}, errors: {} });
  const [rows, setRows] = useState<Record<string, Row[]>>({});
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [ctx, setCtx] = useState<Record<string, string>>({});
  const [log, setLog] = useState<{ ok: boolean; text: string }[]>([]);

  const def = useMemo(() => app.screens.find((s) => s.screen === screen), [screen]);
  const actions = useMemo(() => app.actions.filter((a) => a.screen === screen), [screen]);

  useEffect(() => {
    api.users().then((u) => {
      setUsers(u);
      setUser((cur) => cur || (u[0]?.email ?? ""));
    }, (e: unknown) => setLog((l) => [{ ok: false, text: String(e) }, ...l]));
  }, []);

  const refreshRows = useCallback(async () => {
    if (!user) return;
    const out: Record<string, Row[]> = {};
    for (const t of new Set(actions.filter((a) => a.operation !== "Create").map((a) => a.table))) {
      const c = app.containers.find((x) => x.table === t);
      if (!c) continue;
      try {
        out[t] = await api.list(user, c.entitySet);
      } catch {
        out[t] = [];
      }
    }
    setRows(out);
  }, [actions, user]);

  useEffect(() => {
    void refreshRows();
  }, [refreshRows]);

  useEffect(() => {
    if (!user || !screen) return;
    const t = setTimeout(() => {
      api.evaluate(user, screen, inputs).then(setEv, (e: unknown) =>
        setLog((l) => [{ ok: false, text: e instanceof ApiError ? e.detail : String(e) }, ...l]),
      );
    }, 150);
    return () => clearTimeout(t);
  }, [user, screen, inputs]);

  const prop = (c: ControlDef, p: string): Json | undefined => ev.values[`${c.name}.${p}`];
  const visible = (c: ControlDef) => !c.computed.includes("Visible") || prop(c, "Visible") === true;
  const disabled = (c: ControlDef) => c.computed.includes("DisplayMode") && prop(c, "DisplayMode") !== "Edit";

  /** Value a selected record supplies for a column the legacy formula does not set:
   * the column itself, or the record's id when the column is a lookup to that table. */
  function fromSelection(f: string): Json | undefined {
    for (const [t, id] of Object.entries(selected)) {
      const r = rows[t]?.find((x) => x["id"] === id);
      if (!r) continue;
      if (r[f] !== undefined) return r[f];
      if (f.toLowerCase() === `${t}Id`.toLowerCase()) return r["id"];
    }
    return undefined;
  }

  async function run(a: ActionDef) {
    const rowId = a.operation === "Create" ? null : (selected[a.table] ?? null);
    const context: Record<string, Json> = {};
    for (const f of a.contextFields) {
      const typed = ctx[`${a.control}.${f}`];
      const v = typed !== undefined && typed !== "" ? typed : fromSelection(f);
      if (v !== undefined) context[f] = v;
    }
    try {
      const res = await api.act(user, a.screen, a.control, inputs, context, rowId);
      setLog((l) => [{ ok: true, text: `${a.control}: ${a.operation} ${a.table} ${show(res.record["id"])}` }, ...l]);
      await refreshRows();
      const next = res.navigateTo[0];
      if (next && app.screens.some((s) => s.screen === next)) setScreen(next);
    } catch (e) {
      const text = e instanceof ApiError ? `${e.status} ${e.detail} (correlation ${e.correlationId ?? "-"})` : String(e);
      setLog((l) => [{ ok: false, text: `${a.control}: ${text}` }, ...l]);
    }
  }

  function control(c: ControlDef) {
    if (!visible(c)) return null;
    const rule = Object.entries(c.rules)
      .map(([p, r]) => `${p}: ${r}`)
      .join(", ");
    const meta = <small title={c.source}>{c.source}{rule ? ` · ${rule}` : ""}</small>;
    const set = (v: Json) => setInputs((s) => ({ ...s, [keyOf(c)]: v }));
    const raw = inputs[keyOf(c)];
    if (c.widget === "button") {
      const a = actions.find((x) => x.control === c.name);
      return (
        <div className="field" key={c.name}>
          <span />
          <button className="primary" disabled={disabled(c) || !a} onClick={() => a && void run(a)} data-control={c.name}>
            {c.label ?? c.name}
          </button>
          {meta}
        </div>
      );
    }
    let widget;
    if (c.widget === "text")
      widget = <input id={c.name} value={typeof raw === "string" ? raw : ""} onChange={(e) => set(e.target.value)} />;
    else if (c.widget === "date") {
      const def = prop(c, "DefaultDate");
      const shown = typeof raw === "string" ? raw : typeof def === "string" ? def.slice(0, 10) : "";
      widget = <input id={c.name} type="date" value={shown} onChange={(e) => set(e.target.value || null)} />;
    }
    else if (c.widget === "checkbox")
      widget = <input id={c.name} type="checkbox" checked={raw === true} onChange={(e) => set(e.target.checked)} />;
    else if (c.widget === "select" && !c.options?.length)
      // Items is data-bound (not a static literal): accept the value as free text.
      widget = <input id={c.name} value={typeof raw === "string" ? raw : ""} onChange={(e) => set(e.target.value || null)} />;
    else if (c.widget === "select")
      widget = (
        <select id={c.name} value={typeof raw === "string" ? raw : ""} onChange={(e) => set(e.target.value || null)}>
          <option value="">(blank)</option>
          {(c.options ?? []).map((o) => <option key={o}>{o}</option>)}
        </select>
      );
    else
      widget = (
        <span className="computed" id={c.name}>
          {c.computed.includes("Text") ? show(prop(c, "Text")) : c.type}
          {ev.errors[`${c.name}.Text`] ? <span className="error"> {ev.errors[`${c.name}.Text`]}</span> : null}
        </span>
      );
    return (
      <div className="field" key={c.name}>
        <label htmlFor={c.name}>{c.name}</label>
        {widget}
        {meta}
      </div>
    );
  }

  return (
    <>
      <header>
        <h1>{app.appId} (migrated)</h1>
        <label>
          Signed in as{" "}
          <select value={user} onChange={(e) => setUser(e.target.value)} aria-label="demo user">
            {users.map((u) => (
              <option key={u.email} value={u.email}>{`${u.email} (${u.role})`}</option>
            ))}
          </select>
        </label>
      </header>
      <nav>
        {app.screens.map((s) => (
          <button key={s.screen} aria-current={s.screen === screen ? "page" : undefined} onClick={() => setScreen(s.screen)}>
            {s.screen}
          </button>
        ))}
      </nav>
      <main>
        <section>
          <h2>{screen}</h2>
          {[...new Set(actions.filter((a) => a.operation !== "Create").map((a) => a.table))].map((t) => (
            <div className="field" key={t}>
              <label htmlFor={`row-${t}`}>{t} record</label>
              <select id={`row-${t}`} value={selected[t] ?? ""} onChange={(e) => setSelected((s) => ({ ...s, [t]: e.target.value }))}>
                <option value="">(none)</option>
                {(rows[t] ?? []).map((r) => <option key={show(r["id"])} value={show(r["id"])}>{show(r["id"])}</option>)}
              </select>
            </div>
          ))}
          {(def?.controls ?? []).filter(isInput).map(control)}
          {actions.filter((a) => a.contextFields.length > 0).map((a) => (
            <fieldset key={a.control}>
              <legend>{`${a.control}: required ${a.table} columns the legacy formula does not set`}</legend>
              {a.contextFields.map((f) => {
                const id = `ctx-${a.control}-${f}`;
                return (
                  <div className="field" key={f}>
                    <label htmlFor={id}>{f}</label>
                    <input
                      id={id}
                      value={ctx[`${a.control}.${f}`] ?? ""}
                      placeholder={show(fromSelection(f))}
                      onChange={(e) => setCtx((s) => ({ ...s, [`${a.control}.${f}`]: e.target.value }))}
                    />
                  </div>
                );
              })}
            </fieldset>
          ))}
          {(def?.controls ?? []).filter((c) => !isInput(c)).map(control)}
        </section>
        <section>
          <h2>Activity</h2>
          {log.length === 0 ? <p>No actions yet.</p> : null}
          {log.map((l, i) => (
            <p key={i} className={l.ok ? "ok" : "error"}>{l.text}</p>
          ))}
        </section>
      </main>
    </>
  );
}
