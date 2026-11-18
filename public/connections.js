const byId = id => document.getElementById(id);

async function json(path, body) {
  const response = await fetch(path, {cache:'no-store', credentials:'same-origin',
    ...(body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '办公室暂时无法处理请求。');
  return result;
}

export function mountConnections({notify}) {
  const dialog = byId('slots-dialog'), message = byId('slot-message'), list = byId('slot-list');
  let current = '', loading = false;
  function clearSecret() {
    byId('slot-token').value = '';
    byId('slot-secret').hidden = true;
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const {slots,workerPort} = await json('/api/slots');
      byId('slot-port').textContent = workerPort
        ? '本机连接端口为 ' + workerPort + '。同事从另一台电脑连接时，用 SSH 将这个端口转发到他自己的电脑。连接包内有完整命令。'
        : '协作端口当前无法监听。请检查端口占用后重新启动工作室服务。';
      const signature = JSON.stringify(slots);
      if (current === signature) return;
      current = signature; list.replaceChildren();
      for (const [index,slot] of slots.entries()) {
        const row = document.createElement('div'); row.className = 'slot-row';
        const name = document.createElement('strong'); name.textContent = slot.name;
        const state = document.createElement('small'); state.textContent = '协作 '+String(index+1).padStart(2,'0')+' · '+(slot.online ? '在线' : '等待连接');
        const button = document.createElement('button'); button.className = 'secondary'; button.textContent = '撤销';
        button.addEventListener('click',async () => {
          if (!window.confirm('撤销「'+slot.name+'」的接入令牌并移除席位？')) return;
          button.disabled = true;
          try {
            await json('/api/slots/revoke',{id:slot.id});
            clearSecret(); await refresh(); message.textContent = '已撤销该席位的访问权限。';
          } catch(error) { message.textContent = error.message; button.disabled = false; }
        });
        const text = document.createElement('span'); text.append(name,state);
        row.append(text,button); list.append(row);
      }
    } catch(error) { if(dialog.open) message.textContent=error.message; }
    finally { loading = false; }
  }
  byId('open-slots').onclick=()=>{message.textContent=''; dialog.showModal(); void refresh();};
  byId('create-slot').addEventListener('submit', async e=>{
    e.preventDefault();
    const button=e.target.querySelector('button'); if(button.disabled) return;
    button.disabled=true;
    try {
      const slot=await json('/api/slots',{name:byId('slot-name').value.trim()});
      byId('slot-name').value=''; byId('slot-token').value=slot.token;
      byId('slot-secret').hidden=false; byId('join-help').open=true;
      message.textContent='已创建「'+slot.name+'」，请把令牌单独发给这位同事。';
      await refresh();
    } catch(error) {message.textContent=error.message;} finally {button.disabled=false;}
  });
  async function copyField(field, success) {
    try {await navigator.clipboard.writeText(field.value); notify(success);}
    catch {if(field.type==='password')field.type='text';field.focus();field.select();notify('已选中，请按 Ctrl+C 复制。');}
  }
  byId('copy-token').onclick=()=>copyField(byId('slot-token'),'已复制该席位的接入令牌。');
  dialog.addEventListener('close',()=>{clearSecret();byId('slot-token').type='password';});
  setInterval(()=>{if(!document.hidden && dialog.open) void refresh();},6000);

  const dot=byId('dot-dialog'), invite=byId('dot-invitation'), dotLink=byId('dot-link');
  async function openDot() {
    if (!dot.open) dot.showModal();
    invite.value=''; byId('copy-dot').disabled=true; dotLink.hidden=true; byId('dot-last').textContent='正在读取本机连接信息…';
    try {
      const data=await json('/api/dot/connection');
      invite.value=data.invitation; byId('copy-dot').disabled=!invite.value;
      const url=new URL(data.url);
      if(url.protocol==='https:' && url.hostname==='chatgpt.com') {
        dotLink.href=url.href; dotLink.hidden=false;
      }
      byId('dot-last').textContent=data.connectedAt?'最近一次领取检查 · '+new Date(data.connectedAt).toLocaleString('zh-CN'):'等待 Dot 首次领取。';
    } catch {byId('dot-last').textContent='暂时无法读取 Dot 连接，请稍后重试。';}
  }
  byId('copy-dot').onclick=()=>copyField(invite,'已复制 Dot 入驻指令。');
  byId('dot-profile').onclick=openDot; document.addEventListener('office-dot',openDot);

  const host=window.chrome?.webview, toggle=byId('wall-switch');
  if (host && new URLSearchParams(location.search).get('desktop')==='1') {
    toggle.hidden=false;
    host.addEventListener('message',event=>{
      const msg=event.data;
      if(msg?.type!=='wallpaper')return;
      toggle.disabled=Boolean(msg.busy); toggle.setAttribute('aria-pressed',String(Boolean(msg.enabled)));
      toggle.textContent=msg.busy?'正在切换…':msg.enabled?'关闭桌面壁纸':'开启桌面壁纸';
      if(msg.error)notify(msg.error);
    });
    toggle.onclick=()=>host.postMessage('toggle-wallpaper');
    host.postMessage('wallpaper-status');
  }
}
