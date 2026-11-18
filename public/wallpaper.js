import {mountOffice} from './scene.js';
import {daylight, updateMarket} from './office-environment.js';

const status = document.querySelector('#wall-status');
try {
  const scene = mountOffice(document.querySelector('#canvas'), {wallpaper:true});
  let nextMarket = 0, polling = false, lighting, loadedVersion, pendingVersion;
  async function update() {
    if (polling || document.hidden) return;
    polling = true;
    const mode = daylight();
    if (lighting !== mode) {
      lighting = mode;
      scene.setLighting(mode);
      document.querySelector('.viewport').classList.toggle('night', mode === 'night');
    }
    if (Date.now() >= nextMarket) {
      nextMarket = Date.now() + 120000;
      void updateMarket(scene);
    }
    try {
      const response = await fetch('/api/status', {credentials:'omit', signal:AbortSignal.timeout(5000)});
      if (!response.ok) throw Error();
      const {agents, guestSeats, assetVersion} = await response.json();
      if (assetVersion) {
        loadedVersion ??= assetVersion;
        if (assetVersion !== loadedVersion && pendingVersion === assetVersion) {
          location.reload();
          return;
        }
        pendingVersion = assetVersion !== loadedVersion ? assetVersion : null;
      }
      scene.setState(agents);
      scene.setGuests(guestSeats || []);
      status.hidden = true;
    } catch {
      status.textContent = '办公室离线 · 正在重连';
      status.hidden = false;
    } finally { polling = false; }
  }
  update();
  const pollTimer=setInterval(update, 6000);
  document.addEventListener('visibilitychange', update);
  window.addEventListener('pagehide', event=>{
    if (event.persisted) return;
    clearInterval(pollTimer);
    document.removeEventListener('visibilitychange', update);
    scene.dispose();
  });
} catch {
  status.hidden = false;
  status.textContent = '场景加载失败，请从工作室重新开启壁纸。';
}
