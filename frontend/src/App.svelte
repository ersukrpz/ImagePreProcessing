<script>
  import ControlBar from "./components/ControlBar.svelte";
  import CameraManager from "./components/CameraManager.svelte";
  import LiveCamera from "./components/LiveCamera.svelte";
  import Notifications from "./components/Notifications.svelte";
</script>

<div class="container">
  <div class="card" style="margin-bottom:12px;">
    <ControlBar />
  </div>

  <div class="grid-3" style="grid-template-columns: 320px 1fr 380px;">
    <CameraManager />
    <LiveCamera />
    <Notifications />
  </div>
</div>
