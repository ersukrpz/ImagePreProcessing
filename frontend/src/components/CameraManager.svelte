<script>
  import { API } from "./store.js";
  let cameras = [];
  let id = "";
  let ip = "";

  async function load() {
    const r = await fetch(`${API}/cameras`);
    cameras = await r.json();
  }

  async function addCamera() {
    if (!id || !ip) {
      alert("ID ve RTSP zorunlu");
      return;
    }
    const res = await fetch(`${API}/cameras`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ip }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({ detail: "Hata" }));
      alert(`Ekleme hatası: ${e.detail || res.statusText}`);
      return;
    }
    id = "";
    ip = "";
    await load();
    window.dispatchEvent(new CustomEvent("cameras-updated"));
  }

  async function delCamera(cid) {
    if (!confirm(`${cid} silinsin mi?`)) return;
    const res = await fetch(`${API}/cameras/${encodeURIComponent(cid)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({ detail: "Hata" }));
      alert(`Silme hatası: ${e.detail || res.statusText}`);
      return;
    }
    await load();
    window.dispatchEvent(new CustomEvent("cameras-updated"));
  }

  load();
</script>

<section class="card">
  <h3>Kameralar</h3>

  <div class="col" style="margin-bottom:12px;">
    <input class="input" placeholder="id (örn: giris)" bind:value={id} />
    <input
      class="input mono"
      placeholder="rtsp://user:pass@ip:554/..."
      bind:value={ip}
    />
    <button class="btn btn-primary" on:click={addCamera}>Ekle</button>
  </div>

  <ul class="list">
    {#each cameras as cam}
      <li class="list-item">
        <div class="col" style="min-width:0;">
          <div><b>{cam.id}</b> <span class="badge">RTSP</span></div>
          <div
            class="mono"
            style="font-size:12px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:280px;"
          >
            {cam.ip}
          </div>
        </div>
        <button class="btn btn-danger" on:click={() => delCamera(cam.id)}
          >Sil</button
        >
      </li>
    {/each}
  </ul>
</section>
