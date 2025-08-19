<script>
  import { API } from "./store.js";

  let events = [];
  let es;

  // Aynı (cam+label) 10 sn içinde spam'i kes
  const UI_COOLDOWN_MS = 10000;
  const lastShown = new Map();

  // Full resme geçişi kontrol etmek için deneme sayacı
  const retries = new Map(); // id -> count
  const MAX_RETRY = 6;

  function shouldShow(ev) {
    const key = `${ev.cam_id}|${ev.label}`;
    const now = ev.ts || Date.now();
    const last = lastShown.get(key) || 0;
    if (now - last < UI_COOLDOWN_MS) return false;
    lastShown.set(key, now);
    return true;
  }

  function connect() {
    if (es) es.close();
    es = new EventSource(`${API}/events`);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (!shouldShow(data)) return;
        // full görseli arka planda preload dene; thumb hemen görünsün
        data._full = `${API}/output/${data.image}`;
        events = [data, ...events].slice(0, 200);
      } catch {}
    };
    es.onerror = () => {
      es && es.close();
      setTimeout(connect, 1500);
    };
  }
  connect();

  function fmt(ts) {
    const d = new Date(ts);
    return d.toLocaleString("tr-TR", { hour12: false });
  }

  function tryUpgradeToFull(ev, imgEl) {
    // küçük gecikmeyle full resmi dene (dosya tam yazılsın)
    setTimeout(() => {
      const n = (retries.get(ev.id) || 0) + 1;
      retries.set(ev.id, n);
      const bust = `${ev._full}?r=${Date.now()}&n=${n}`;
      // preload
      const test = new Image();
      test.onload = () => { imgEl.src = bust; };             // başarı → full'e geç
      test.onerror = () => {
        if (n < MAX_RETRY) tryUpgradeToFull(ev, imgEl);      // tekrar dene
      };
      test.src = bust;
    }, 200); // 200ms sonra başla
  }
</script>

<section class="card" style="max-height: calc(100vh - 48px); overflow:auto;">
  <h3>Bildirimler</h3>

  {#if events.length === 0}
    <div style="color:var(--muted);">Henüz bildirim yok.</div>
  {/if}

  <div class="col">
    {#each events as ev}
      <article style="display:flex; gap:10px; border:1px solid var(--border); border-radius:10px; padding:8px; background:#0b1528;">
        <!-- Önce THUMB göster; component mount olunca full'e yükselt -->
        <img
          bind:this={ev._imgRef}
          src={ev.thumb ? `data:image/jpeg;base64,${ev.thumb}` : ev._full}
          alt="snapshot"
          class="img-frame"
          style="width:128px; height:80px; aspect-ratio:auto; border-radius:8px;"
          on:load={() => { if (ev.thumb) tryUpgradeToFull(ev, ev._imgRef); }}
          on:error={(e) => { /* thumb yok + full hata → gizle */ e.target.style.display='none'; }}
        />
        <div style="flex:1; min-width:0;">
          <div class="row" style="justify-content:space-between;">
            <strong>{ev.label}</strong>
            <span class="label">{fmt(ev.ts)}</span>
          </div>
          <div style="font-size:13px; color:#cdd8ea; margin-top:4px;">
            Kamera: <b>{ev.cam_id}</b>
            {#if ev.dominant_color} • Renk: <b>{ev.dominant_color}</b>{/if}
            {#if ev.score !== undefined} • Skor: {ev.score}{/if}
          </div>
        </div>
      </article>
    {/each}
  </div>
</section>
