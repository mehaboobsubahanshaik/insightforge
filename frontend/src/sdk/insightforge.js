/* InsightForge JS SDK v1 (MVP4 E2). UMD-style global: window.InsightForge.
   embed(): drops a secure iframe. query(): headless data for your own charts.
   Tokens are minted SERVER-SIDE by your backend (POST /api/v1/embed/tokens
   with your InsightForge session/API auth) — never expose vendor creds. */
(function (root) {
  function embed(opts) {
    var el = typeof opts.container === "string"
      ? document.querySelector(opts.container) : opts.container;
    if (!el) throw new Error("InsightForge.embed: container not found");
    var base = (opts.baseUrl || "").replace(/\/$/, "");
    var f = document.createElement("iframe");
    f.src = base + "/embed.html?token=" + encodeURIComponent(opts.token);
    f.style.width = opts.width || "100%";
    f.style.height = opts.height || "480px";
    f.style.border = "0";
    f.setAttribute("title", opts.title || "InsightForge dashboard");
    el.innerHTML = "";
    el.appendChild(f);
    return { destroy: function () { f.remove(); },
             reload: function () { f.src = f.src; } };
  }
  function query(opts) {
    var base = (opts.baseUrl || "").replace(/\/$/, "");
    var url = base + "/api/v1/embed/" + encodeURIComponent(opts.token)
      + "/query?formula=" + encodeURIComponent(opts.formula)
      + (opts.groupBy ? "&group_by=" + encodeURIComponent(opts.groupBy) : "");
    return fetch(url).then(function (r) {
      if (!r.ok) return r.json().then(function (e) {
        throw new Error(e.detail || r.statusText); });
      return r.json();
    });
  }
  root.InsightForge = { embed: embed, query: query, version: "1.0.0" };
})(typeof window !== "undefined" ? window : this);
