/* InsightForge React SDK v1 (MVP4 E2). Copy-in components (no npm package
   yet): <InsightForgeDashboard/> for the secure iframe, useInsightForgeQuery
   for headless data. Mint tokens server-side; pass them as props. */
import { useEffect, useRef, useState } from "react";

export function InsightForgeDashboard({ token, baseUrl = "", height = 480,
                                        title = "InsightForge dashboard" }) {
  const src = `${baseUrl.replace(/\/$/, "")}/embed.html?token=${encodeURIComponent(token)}`;
  return (
    <iframe src={src} title={title} style={{ width: "100%", height, border: 0 }} />
  );
}

export function useInsightForgeQuery({ token, formula, groupBy, baseUrl = "" }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setState({ loading: true, data: null, error: null });
    const url = `${baseUrl.replace(/\/$/, "")}/api/v1/embed/`
      + `${encodeURIComponent(token)}/query?formula=${encodeURIComponent(formula)}`
      + (groupBy ? `&group_by=${encodeURIComponent(groupBy)}` : "");
    fetch(url)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        return r.json();
      })
      .then((data) => alive.current && setState({ loading: false, data, error: null }))
      .catch((error) => alive.current && setState({ loading: false, data: null, error }));
    return () => { alive.current = false; };
  }, [token, formula, groupBy, baseUrl]);
  return state;
}
