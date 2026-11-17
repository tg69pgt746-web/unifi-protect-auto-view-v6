/* UniFi Protect Auto-View: camera viewer panel for Home Assistant. */
const DETECTION_EVENT = "unifi_protect_auto_view_detection";
const PREFS_KEY = "unifi_protect_auto_view_viewer";
const DEFAULT_PREFS = { columns: "auto", live: true, package: false, autoFocus: true };

const cleanName = (n) =>
  (n || "").replace(/\s+(high|medium|low)(\s+resolution)?(\s+channel)?(\s+\(insecure\))?$/i, "");

class UnifiProtectViewer extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._prefs = this._loadPrefs();
    this._cards = new Map();
    this._tiles = new Map();
    this._built = false;
    this._focusCard = null;
    this._focusTimer = null;
    this._unsub = null;
    this._camKey = "";
  }

  /* ---- HA panel API ---- */
  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._built = true;
      this._build();
      return;
    }
    if (this._menu) this._menu.hass = hass;
    this._refresh();
    for (const c of this._cards.values()) c.hass = hass;
    if (this._focusCard) this._focusCard.hass = hass;
  }
  set narrow(v) {
    this._narrow = v;
    if (this._menu) this._menu.narrow = v;
  }
  set panel(p) {
    this._panel = p;
  }
  connectedCallback() {
    this._subscribe();
    this._onKey = (e) => e.key === "Escape" && this._closeFocus();
    window.addEventListener("keydown", this._onKey);
  }
  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((u) => u()).catch(() => {});
      this._unsub = null;
    }
    window.removeEventListener("keydown", this._onKey);
    clearTimeout(this._focusTimer);
  }

  /* ---- prefs ---- */
  _loadPrefs() {
    try {
      return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") };
    } catch (e) {
      return { ...DEFAULT_PREFS };
    }
  }
  _savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(this._prefs));
    } catch (e) {
      /* storage unavailable: ignore */
    }
  }

  /* ---- camera discovery (mirrors the backend logic) ---- */
  _cameras() {
    const h = this._hass;
    const byDevice = new Map();
    for (const [eid, ent] of Object.entries(h.entities || {})) {
      if (!eid.startsWith("camera.") || ent.platform !== "unifiprotect" || ent.hidden) continue;
      const key = ent.device_id || eid;
      if (!byDevice.has(key)) byDevice.set(key, []);
      byDevice.get(key).push(eid);
    }
    const out = [];
    for (const [key, list] of byDevice) {
      const dev = h.devices && h.devices[key];
      const base =
        (dev && (dev.name_by_user || dev.name)) ||
        cleanName(h.states[list[0]] && h.states[list[0]].attributes.friendly_name) ||
        list[0];
      const pkg = list.filter((e) => /package/.test(e)).sort();
      const usable = list.filter((e) => !/package/.test(e)).sort();
      const pool = usable.length ? usable : [...list].sort();
      const high = pool.filter((e) => /(^|[._])high([._]|$)/.test(e));
      out.push({ eid: (high[0] || pool[0]), name: base });
      if (this._prefs.package && usable.length) {
        for (const p of pkg) out.push({ eid: p, name: `${base} (package)` });
      }
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
  }

  /* ---- build ---- */
  async _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; height:100%; background:var(--primary-background-color); color:var(--primary-text-color); }
        .bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:8px 16px; min-height:56px; box-sizing:border-box;
               background:var(--app-header-background-color, var(--primary-color)); color:var(--app-header-text-color, #fff); }
        .bar h1 { font-size:20px; font-weight:400; margin:0; flex:1; }
        .bar label { display:flex; align-items:center; gap:4px; font-size:13px; white-space:nowrap; }
        .bar select { font:inherit; font-size:13px; }
        .wrap { padding:12px; overflow:auto; height:calc(100% - 56px); box-sizing:border-box; }
        .grid { display:grid; gap:12px; }
        .tile { position:relative; border-radius:12px; overflow:hidden; background:var(--card-background-color, #222);
                box-shadow:var(--ha-card-box-shadow, 0 1px 4px rgba(0,0,0,.3)); aspect-ratio:16/9; }
        .tile .vid, .tile .vid > * { display:block; width:100%; height:100%; }
        .hit { position:absolute; inset:0; cursor:pointer; background:transparent; border:0; }
        .label { position:absolute; left:0; right:0; bottom:0; padding:6px 10px; font-size:14px; color:#fff; pointer-events:none;
                 background:linear-gradient(transparent, rgba(0,0,0,.7)); }
        .empty { padding:48px 16px; text-align:center; opacity:.7; }
        .focus { position:fixed; inset:0; z-index:20; background:rgba(0,0,0,.92); display:none; flex-direction:column; }
        .focus.open { display:flex; }
        .focus .top { display:flex; align-items:center; gap:12px; padding:12px 16px; color:#fff; }
        .focus .top .t { flex:1; font-size:18px; }
        .focus .top .t small { display:block; font-size:12px; opacity:.7; }
        .focus button { font:inherit; padding:8px 16px; border-radius:8px; border:0; cursor:pointer; }
        .focus .body { flex:1; min-height:0; display:flex; align-items:center; justify-content:center; padding:0 12px 12px; }
        .focus .body > * { width:100%; max-width:min(100%, calc((100vh - 90px) * 16 / 9)); }
        .alert .t { color:#ffb74d; }
      </style>
      <div class="bar">
        <ha-menu-button></ha-menu-button>
        <h1>Cameras</h1>
        <label>Columns
          <select id="cols">
            <option value="auto">Auto</option><option value="1">1</option>
            <option value="2">2</option><option value="3">3</option><option value="4">4</option>
          </select>
        </label>
        <label><input type="checkbox" id="live"> Live video</label>
        <label><input type="checkbox" id="pkg"> Package cams</label>
        <label><input type="checkbox" id="af"> Jump to events</label>
      </div>
      <div class="wrap"><div class="grid" id="grid"></div></div>
      <div class="focus" id="focus">
        <div class="top"><div class="t" id="ftitle"></div><button id="fclose">Close</button></div>
        <div class="body" id="fbody"></div>
      </div>`;

    const $ = (id) => this.shadowRoot.getElementById(id);
    this._grid = $("grid");
    this._menu = this.shadowRoot.querySelector("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;

    $("cols").value = this._prefs.columns;
    $("live").checked = this._prefs.live;
    $("pkg").checked = this._prefs.package;
    $("af").checked = this._prefs.autoFocus;
    $("cols").onchange = (e) => { this._prefs.columns = e.target.value; this._savePrefs(); this._applyColumns(); };
    $("live").onchange = (e) => { this._prefs.live = e.target.checked; this._savePrefs(); this._rebuildCards(); };
    $("pkg").onchange = (e) => { this._prefs.package = e.target.checked; this._savePrefs(); this._rebuildCards(); };
    $("af").onchange = (e) => { this._prefs.autoFocus = e.target.checked; this._savePrefs(); };
    $("fclose").onclick = () => this._closeFocus();
    $("focus").onclick = (e) => { if (e.target.id === "focus") this._closeFocus(); };

    try {
      this._helpers = await window.loadCardHelpers();
    } catch (e) {
      this._grid.innerHTML = `<div class="empty">Could not load Home Assistant card helpers.</div>`;
      return;
    }
    this._applyColumns();
    await this._rebuildCards();
    this._subscribe();
  }

  _applyColumns() {
    const c = this._prefs.columns;
    this._grid.style.gridTemplateColumns =
      c === "auto" ? "repeat(auto-fill, minmax(min(100%, 340px), 1fr))" : `repeat(${c}, minmax(0, 1fr))`;
  }

  async _makeCard(eid, live) {
    const el = await this._helpers.createCardElement({
      type: "picture-entity",
      entity: eid,
      camera_image: eid,
      camera_view: live ? "live" : "auto",
      show_name: false,
      show_state: false,
      tap_action: { action: "none" },
      hold_action: { action: "none" },
    });
    el.hass = this._hass;
    return el;
  }

  /* Rebuild every tile (used when mode or camera set changes). */
  async _rebuildCards() {
    if (!this._helpers || !this._hass) return;
    const cams = this._cameras();
    this._camKey = cams.map((c) => c.eid).join("|") + `|${this._prefs.live}`;
    this._cards.clear();
    this._grid.innerHTML = "";
    if (!cams.length) {
      this._grid.innerHTML = `<div class="empty">No UniFi Protect cameras found. Set up the UniFi Protect integration first.</div>`;
      return;
    }
    for (const cam of cams) {
      const tile = document.createElement("div");
      tile.className = "tile";
      const vid = document.createElement("div");
      vid.className = "vid";
      const card = await this._makeCard(cam.eid, this._prefs.live);
      vid.appendChild(card);
      this._cards.set(cam.eid, card);
      const hit = document.createElement("button");
      hit.className = "hit";
      hit.title = `Enlarge ${cam.name}`;
      hit.onclick = () => this._openFocus(cam.eid, cam.name, false);
      const label = document.createElement("div");
      label.className = "label";
      label.textContent = cam.name;
      tile.append(vid, hit, label);
      this._grid.appendChild(tile);
    }
  }

  /* Cameras may be added/removed while the panel is open. */
  _refresh() {
    if (!this._helpers) return;
    const key = this._cameras().map((c) => c.eid).join("|") + `|${this._prefs.live}`;
    if (key !== this._camKey) this._rebuildCards();
  }

  /* ---- focus (enlarged) view ---- */
  async _openFocus(eid, name, auto, kindTitle) {
    clearTimeout(this._focusTimer);
    const $ = (id) => this.shadowRoot.getElementById(id);
    const body = $("fbody");
    body.innerHTML = "";
    this._focusCard = await this._makeCard(eid, true);
    body.appendChild(this._focusCard);
    const top = this.shadowRoot.querySelector(".focus .top");
    top.classList.toggle("alert", !!auto);
    $("ftitle").innerHTML = "";
    const t = document.createElement("span");
    t.textContent = kindTitle || name;
    $("ftitle").appendChild(t);
    if (auto) {
      const s = document.createElement("small");
      s.textContent = "Auto-opened by detection";
      $("ftitle").appendChild(s);
    }
    $("focus").classList.add("open");
    if (auto) {
      const secs = Number(this._panel && this._panel.config && this._panel.config.timeout) || 45;
      this._focusTimer = setTimeout(() => this._closeFocus(), secs * 1000);
    }
  }

  _closeFocus() {
    clearTimeout(this._focusTimer);
    const f = this.shadowRoot && this.shadowRoot.getElementById("focus");
    if (f) f.classList.remove("open");
    const body = this.shadowRoot && this.shadowRoot.getElementById("fbody");
    if (body) body.innerHTML = "";
    this._focusCard = null;
  }

  /* ---- detection events from the integration ---- */
  _subscribe() {
    if (this._unsub || !this._hass || !this._hass.connection) return;
    this._unsub = this._hass.connection.subscribeEvents((ev) => {
      if (!this._prefs.autoFocus || !this._helpers) return;
      const d = ev.data || {};
      if (!d.camera) return;
      this._openFocus(d.camera, d.camera, true, d.title);
    }, DETECTION_EVENT);
  }
}

customElements.define("unifi-protect-viewer", UnifiProtectViewer);
