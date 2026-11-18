export function daylight(now = new Date()) {
  const hour = Number(new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Shanghai', hour:'2-digit', hourCycle:'h23'}).format(now));
  return hour >= 7 && hour < 19 ? 'day' : 'night';
}

export async function updateMarket(scene) {
  if (!scene) return;
  try {
    const response = await fetch('https://api.coinbase.com/v2/prices/BTC-USD/spot', {
      credentials:'omit', referrerPolicy:'no-referrer', signal:AbortSignal.timeout(5500)
    });
    if (!response.ok) throw Error();
    const {data} = await response.json();
    const price = Number(data.amount);
    if (data.currency !== 'USD' || !Number.isFinite(price) || price <= 0) throw Error();
    scene.setMarket({price, updatedAt:new Date().toISOString()});
  } catch { scene.setMarket({price:null}); }
}
