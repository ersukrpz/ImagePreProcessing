<script>
    import { API } from "./store.js";

    let cameras = [];
    let selectedId = "";
    let src = "";

    async function load() {
        const r = await fetch(`${API}/cameras`);
        cameras = await r.json();
        if (cameras.length) {
            if (!selectedId || !cameras.find((c) => c.id === selectedId)) {
                selectedId = cameras[0].id;
            }
            setSrc();
        } else {
            selectedId = "";
            src = "";
        }
    }

    function setSrc() {
        if (!selectedId) return;
        src = `${API}/video/${encodeURIComponent(selectedId)}?t=${Date.now()}`;
    }

    function reload() {
        setTimeout(setSrc, 1200);
    }
    function onCamerasUpdated() {
        load();
    }

    window.addEventListener("cameras-updated", onCamerasUpdated);
    load();
</script>

<section class="card">
    <div class="row" style="margin-bottom:8px;">
        <span class="label">Kamera</span>
        <select class="select" bind:value={selectedId} on:change={setSrc}>
            {#each cameras as cam}
                <option value={cam.id}>{cam.id}</option>
            {/each}
        </select>
    </div>

    {#if src}
        <img class="img-frame" {src} alt="live" on:error={reload} />
    {:else}
        <div style="color:var(--muted);">
            Kamera yok. Soldan ekleyin veya <span class="mono"
                >data/cameras.json</span
            >’a yazın.
        </div>
    {/if}
</section>
