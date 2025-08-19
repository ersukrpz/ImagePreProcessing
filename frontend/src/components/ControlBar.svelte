<script>
    import { API } from "./store.js";
    let running = false;

    async function refresh() {
        try {
            const r = await fetch(`${API}/control/status`);
            const d = await r.json();
            running = !!d.enabled;
        } catch (e) {}
    }
    async function start() {
        await fetch(`${API}/control/start`, { method: "POST" });
        refresh();
    }
    async function stop() {
        await fetch(`${API}/control/stop`, { method: "POST" });
        refresh();
    }
    refresh();
</script>

<section
    class="card row"
    style="align-items:center; justify-content:space-between;"
>
    <div class="row" style="gap:8px;">
        <button class="btn btn-primary" on:click={start} disabled={running}
            >Başlat</button
        >
        <button class="btn btn-danger" on:click={stop} disabled={!running}
            >Durdur</button
        >
    </div>
    <span class="label">Durum: {running ? "Çalışıyor" : "Durdu"}</span>
</section>
