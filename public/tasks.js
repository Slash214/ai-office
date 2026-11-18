const phaseNames = {
  planning: '方案规划', reviewing: '审核分工', awaiting_approval: '等待总裁审批',
  executing: '团队执行', complete: '已完成', stopped: '已停止',
};
const kindNames = { plan: '规划', review: '审核与分工', approval: '审批派发', execution: '执行' };
const discussionNames = { revision: '按审核意见修订', 'final-review': '复审修订方案' };
const stateNames = { pending: '待接力', queued: '排队中', running: '正在运行', done: '已完成', error: '需要处理', handoff: '等待会话交付', cancelled: '已停止' };
const dateFormat = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

export function mountTasks({ roster, notify, icon, esc }) {
  const byId = id => document.getElementById(id);
  const dispatch = byId('dispatch'), list = byId('task-list'), count = byId('task-count');
  const compose = byId('compose'), form = byId('new-task'), brief = byId('brief');
  const submit = form.querySelector('[type="submit"]');
  const detail = byId('task-detail'), content = byId('task-content');
  const preview = byId('release-preview'), previewStatus = byId('preview-status'), previewView = byId('preview-view');
  const previewCode = byId('preview-code'), previewDiff = byId('preview-diff');
  const drafts = new Map();
  let previewRequest = null;
  let submission = null;
  let tasks = [], caps = {}, demo = false, selected = null;
  let requestedTask = new URL(location.href).searchParams.get('task');
  let loaded = false, loading = false, revision = 0, writing = false, listError = '';
  let listMark = '', detailMark = '';
  let listTag = '';
  const name = (id, task) => id === 'president' ? '总裁' : roster[id]?.name || task?.workerNames?.[id] || id;
  const selectedTask = () => tasks.find(task => task.id === selected);
  const key = (task, step) => task.id + '/' + step.id;
  const current = task => task.steps.find(step => step.id === task.currentStep);
  const taskPath = task => '/api/tasks/' + encodeURIComponent(task.id);
  const candidate = task => task.release ? { releaseId: task.release.id } : {};
  const formatTime = value => Number.isFinite(Date.parse(value)) ? dateFormat.format(new Date(value)) : '';

  async function api(path, data) {
    if (data && demo) throw new Error('请先切回实时模式，再处理本机任务。');
    const response = await fetch(path, data ? {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    } : { credentials: 'same-origin', cache: 'no-store', headers: listTag && path === '/api/tasks' ? {'If-None-Match':listTag} : {} });
    if (!data && response.status === 304) return null;
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error('办公室服务返回了无效响应。请检查本地服务。');
    }
    if (!response.ok) throw new Error(result.error || '请求失败，请稍后重试。');
    if (!data) result.etag = response.headers.get('ETag') || '';
    return result;
  }

  function statusLabel(task) {
    const step = current(task);
    if (task.stoppedAt) return '已停止';
    if (task.rolledBackAt) return '已回退';
    if (!step) return task.acceptedAt ? '已验收' : '待验收';
    if (step.status === 'queued') return '已排队 · 等待 '+name(step.agent,task);
    if (step.status === 'handoff' && task.workerNames?.[step.agent]) return name(step.agent,task)+(step.claimed?' · 连接器执行中':' · 等待领取');
    if (step.status === 'handoff') return name(step.agent,task)+' · 会话交接';
    if (step.status === 'error') return name(step.agent,task) + ' · 待处理';
    if (discussionNames[step.id]) return discussionNames[step.id];
    return phaseNames[task.status] || kindNames[step.kind];
  }

  function renderList() {
    const msg = demo ? '演示模式 · 切回实时可查看本机任务。' :
      listError || (!loaded ? '正在读取本机任务…' : '');
    const signature = JSON.stringify([msg, tasks.map(t => [t.id, t.updatedAt, statusLabel(t)])]);
    if (signature === listMark) return;
    listMark = signature;
    const focusedId = list.contains(document.activeElement) ? document.activeElement.dataset.task : null;
    count.textContent = demo ? '模拟数据' : tasks.length ? tasks.length + ' 项 · 本机私有' : '本机私有';
    const rows = demo ? '' : tasks.map(task => {
      const short = task.brief.trim().split(/\r?\n/)[0];
      return '<button type="button" class="task-row" data-task="' + esc(task.id) + '">' +
        '<strong>' + esc(short) + '</strong><span>' + esc(statusLabel(task)) + '</span>' +
        '<time datetime="' + esc(task.updatedAt) + '">' + esc(formatTime(task.updatedAt)) + '</time></button>';
    }).join('');
    const empty = msg || (!rows ? '还没有任务。点击「分配任务」，把第一份简报交给 Carbon。' : '');
    list.innerHTML = (empty ? '<div class="empty">' + esc(empty) + '</div>' : '') + rows;
    if (focusedId) [...list.querySelectorAll('[data-task]')].find(b => b.dataset.task === focusedId)?.focus({ preventScroll: true });
  }

  function controls(task, step) {
    if (step.status === 'running') {
      const progress = step.agent === 'codex' ? '本机 Codex 正在工作室项目中开发与验证。' :
        step.kind === 'review' && task.routingMode === 'auto' ? 'Astra 正在审核方案并选择执行人。' : '模型正在处理。';
      return '<p role="status">' + progress + '任务台会自动更新进度。</p><p class="run-time"><span data-started="' +
        esc(step.updatedAt) + '"></span></p>';
    }
    if (step.status === 'queued' || step.status === 'pending') return '<p role="status">任务已派发，轮到此步骤时会自动运行。可以关闭此窗口。</p>';
    const cap = caps[step.agent];
    const isSlot = Boolean(task.workerNames?.[step.agent]);
    const automatic = Boolean(cap?.ready) || (isSlot && step.status==='error');
    const label = '重试此步骤';
    const action = 'retry';
    const detailText = isSlot ? (step.claimed?'已发给同事电脑上的连接器。':'连接器上线后可自动领取此项分工。') :
      cap ? (automatic ? '本机 CLI 可调用，运行会使用该账号额度。' : cap.detail) : '正在检查本机模型连接，也可直接人工交接。';
    const reviewHint = step.id === 'review' ? '<p>需要 Carbon 修订时，让 Astra 在首行单独写 [revise]，并附上具体意见。</p>' : '';
    if (step.agent === 'codex') return '<p>'+esc(cap?.detail || '请检查本机 Codex 的连接状态。')+'</p>' +
      (automatic?'<details data-disclosure="retry-note"><summary>补充开发要求</summary><textarea id="retry-note" data-focus="retry-note" rows="2" maxlength="2000" aria-label="补充开发要求">'+esc(drafts.get(key(task,step)+'/retry') ?? step.feedback ?? '')+'</textarea></details><div class="stage-actions"><button type="button" class="primary" data-focus="model" data-action="retry">重试开发步骤</button>'+
        (task.revisionBase ? '<button type="button" class="secondary" data-action="retry-fresh" data-focus="retry-fresh">从正式版重新生成</button>' : '')+'</div>':'');
    return '<p>' + esc(detailText) + '</p>' +
      '<div class="stage-actions">' +
      (step.agent==='dot' ? '<button type="button" class="secondary" data-focus="dot" data-action="dot">连接我的 Dot</button>' : '') +
      (automatic ? '<button type="button" class="primary" data-focus="model" data-action="' + action + '">' + label + '</button>' : '') +
      '<button type="button" class="secondary" data-focus="copy" data-action="copy">复制交接文本</button></div>' +
      '<details data-disclosure="prompt"><summary>查看交接文本</summary><textarea readonly data-focus="prompt" rows="4" aria-label="交接文本">' + esc(step.prompt) + '</textarea></details>' +
      '<details data-disclosure="manual"' + (automatic ? '' : ' open') + '><summary>人工回填结果</summary>' +
      reviewHint + '<label for="manual-result">来自 ' + esc(name(step.agent,task)) + ' 的结果</label>' +
      '<textarea id="manual-result" data-focus="result" maxlength="16000" rows="4" placeholder="把该成员的实际产出贴在这里…">' +
      esc(drafts.get(key(task, step)) || '') + '</textarea>' +
      '<button type="button" class="secondary" data-focus="manual" data-action="manual">提交结果并继续</button></details>';
  }

  function deliveryControls(task) {
    const release = task.release;
    const accepted = task.acceptedAt;
    let actions;
    if (accepted) {
      const text = task.rolledBackAt ? '已回退 · ' + formatTime(task.rolledBackAt) : '已验收 · ' + formatTime(accepted);
      actions = '<span>'+icon('check')+' '+esc(text)+'</span>';
      if (release && !task.rolledBackAt) actions += '<button type="button" class="secondary" data-action="rollback" data-focus="rollback">一键回退</button>';
      if (release) actions += '<button type="button" class="secondary" data-action="live-office" data-focus="live-office">打开正式办公室</button>';
    } else {
      actions = release
        ? '<button type="button" class="secondary" data-action="preview" data-focus="preview">预览候选版</button>'
        : '';
      actions += '<button type="button" class="primary" data-action="accept" data-focus="accept">'+icon('check')+
        (release ? '验收并发布' : '验收通过')+'</button>';
    }
    const revision = accepted ? '' :
      '<details class="review-feedback" data-disclosure="review-feedback"><summary>打回修改</summary>' +
      '<label for="reject-note">返工意见</label><textarea id="reject-note" data-focus="reject-note" rows="3" maxlength="2000" placeholder="具体说明你希望调整的地方…">' +
      esc(drafts.get(task.id+'/reject') || '') + '</textarea><button type="button" class="secondary" data-action="reject" data-focus="reject">提交意见并返工</button></details>';
    const recovery = release?.changes.some(change => !change.path.startsWith('public/')) && accepted
      ? '<p class="release-note">涉及后台或桌面程序的改动，在相应程序重启或重新构建后生效。</p>' : '';
    return '<div class="delivery-bar">'+actions+revision+recovery+
      '<div class="form-error" role="status" id="action-error"></div></div>';
  }

  function showElapsed() {
    const label = content.querySelector('[data-started]');
    if (!label || !detail.open) return;
    const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(label.dataset.started))/1000));
    if (Number.isFinite(elapsed)) {
      const minutes = Math.floor(elapsed/60);
      label.textContent = '本步骤已运行 '+(minutes ? minutes+' 分 ' : '')+elapsed%60+' 秒';
    }
  }

  function renderDetail() {
    const task = selectedTask();
    if (!detail.open || !task || demo) return;
    const step = current(task);
    const signature = JSON.stringify([task.id, task.updatedAt, task.currentStep, task.acceptedAt, task.rolledBackAt,
      task.stoppedAt, task.release?.id, task.steps.map(s => s.status), caps[step?.agent]]);
    if (detailMark === signature) return;
    const sameTask = content.dataset.taskId === task.id;
    const sameStep = sameTask && content.dataset.currentStep === task.currentStep;
    const active = content.contains(document.activeElement) ? document.activeElement : null;
    const focusKey = active?.dataset.focus;
    const selection = active?.tagName === 'TEXTAREA' ? [active.selectionStart, active.selectionEnd] : null;
    const expanded = new Map([...content.querySelectorAll('details')].map(el => [el.dataset.disclosure, el.open]));
    const scroll = sameTask ? detail.scrollTop : 0;
    detailMark = signature;
    content.dataset.taskId = task.id;
    content.dataset.currentStep = task.currentStep || '';
    const steps = task.steps.filter(item=>item.kind !== 'approval').map(item => {
      const isCurrent = item.id === task.currentStep;
      const state = stateNames[item.status];
      let result = '';
      if (item.result) result = '<details data-disclosure="result-' + esc(item.id) + '"' +
        (item.kind === 'execution' && !task.currentStep ? ' open' : '') +
        '><summary>' + (item.agent==='codex'?'代码改动与测试记录':item.agent==='dot' && item.result.startsWith('来源：总裁办公室从个人 Dot') ? '会话实录 · 人工转交' : '查看成果') + '</summary><div class="result">' + esc(item.result) + '</div></details>';
      if (item.blockedReview && item.result !== item.blockedReview) result += '<details data-disclosure="result-objection"><summary>复审提出的问题</summary><div class="result">' + esc(item.blockedReview) + '</div></details>';
      return '<li class="step"' + (isCurrent ? ' aria-current="step"' : '') + '><h3>' +
        esc(name(item.agent,task)) + ' · ' + esc(discussionNames[item.id] || kindNames[item.kind]) + '<small>' + esc(item.status==='handoff' && task.workerNames?.[item.agent] ? (item.claimed?'执行中':'待领取') : state) + '</small></h3>' +
        (item.kind === 'execution' && task.assignments?.[item.agent] ? '<p class="assignment">'+esc(task.assignments[item.agent])+'</p>' : '') +
        (item.feedback ? '<details data-disclosure="feedback-'+esc(item.id)+'"><summary>总裁补充要求</summary><div class="result">'+esc(item.feedback)+'</div></details>' : '') +
        (item.error ? '<p class="form-error">' + esc(item.error) + '</p>' : '') + result +
        (isCurrent ? controls(task, item) : '') + '</li>';
    }).join('');
    const completed = task.status==='complete' && !step;
    const delivery = completed ? deliveryControls(task) : step
      ? '<div class="delivery-bar"><button type="button" class="secondary stop-action" data-action="stop" data-focus="stop">停止任务</button>' +
        '<div class="form-error" role="status" id="action-error"></div></div>' : '';
    content.innerHTML = '<p class="task-brief">' + esc(task.brief) + '</p><p>'+esc(statusLabel(task))+
      (task.routingMode==='auto'?' · 团队自动分工':' · 自动接力')+'</p>' +
      (task.assignmentReason?'<p>分工理由 · '+esc(task.assignmentReason)+'</p>':'')+
      '<ol class="steps">' + steps + '</ol>'+delivery;
    for (const disclosure of content.querySelectorAll('details')) {
      const id = disclosure.dataset.disclosure;
      if (expanded.has(id) && (sameStep || (sameTask && id.startsWith('result-')))) disclosure.open = expanded.get(id);
    }
    if (sameStep && focusKey) {
      const target = [...content.querySelectorAll('[data-focus]')].find(el => el.dataset.focus === focusKey);
      target?.focus({ preventScroll: true });
      if (selection && target?.tagName === 'TEXTAREA') target.setSelectionRange(...selection);
    }
    detail.scrollTop = scroll;
    lockControls();
    showElapsed();
  }

  function lockControls() {
    submit.disabled = writing;
    for (const el of content.querySelectorAll('button[data-action]:not([data-action="copy"])')) el.disabled = writing;
  }

  function remember(task) {
    ++revision;
    listError = '';
    const index = tasks.findIndex(t => t.id === task.id);
    if (index < 0) tasks.unshift(task);
    else tasks[index] = task;
    loaded = true;
    renderList();
    renderDetail();
  }

  async function refresh() {
    if (loading || demo) return;
    loading = true;
    const at = revision;
    try {
      const data = await api('/api/tasks');
      if (at !== revision || demo) return;
      if (data) { tasks = data.tasks; listTag = data.etag; }
      loaded = true;
      listError = '';
      renderList();
      renderDetail();
      openRequestedTask();
    } catch (error) {
      if (at !== revision || demo) return;
      listError = error instanceof TypeError ? '暂时连接不上本地办公室，正在重连。' : error.message;
      renderList();
    } finally {
      loading = false;
    }
  }

  function openTask(task) {
    if (!task || demo) return;
    selected = task.id;
    detailMark = '';
    if (!detail.open) detail.showModal();
    renderDetail();
  }
  function openRequestedTask() {
    if (!requestedTask || demo || writing || document.querySelector('dialog[open]:not(#task-detail)') ||
        (detail.open && selected !== requestedTask && [...drafts].some(([id, text]) => id.startsWith(selected + '/') && text.trim()))) return;
    const task = tasks.find(row=>row.id===requestedTask);
    if (task) {requestedTask=null;openTask(task)}
  }
  document.addEventListener('close',openRequestedTask,true);

  async function openPreview(task) {
    const request = {};
    previewRequest = request;
    previewStatus.textContent = '正在打开候选版…';
    previewView.hidden = previewCode.hidden = true;
    previewCode.open = false;
    preview.showModal();
    try {
      const data = await api(taskPath(task) + '/preview?releaseId=' + encodeURIComponent(task.release.id));
      if (previewRequest !== request || !preview.open) return;
      if (data.url) {
        const url = new URL(data.url);
        if (url.protocol !== 'http:' || !['127.0.0.1','localhost'].includes(url.hostname) ||
            url.origin === location.origin || url.username || url.password || !url.port) {
          throw Error('候选版预览地址无效。');
        }
        const frame = document.createElement('iframe');
        frame.title = '候选版办公室';
        frame.setAttribute('sandbox', 'allow-scripts allow-same-origin');
        frame.referrerPolicy = 'no-referrer';
        frame.src = url.href;
        previewView.replaceChildren(frame);
        previewView.hidden = false;
        previewStatus.textContent = '候选版使用示例工位状态。通过「验收并发布」应用到正式办公室。';
      } else {
        previewStatus.textContent = '这次修改涉及后台或程序源码，可在下方查看实际文件差异。';
        previewCode.open = true;
      }
      previewDiff.textContent = data.diff;
      previewCode.hidden = false;
    } catch (error) {
      if (previewRequest === request && preview.open) previewStatus.textContent = error.message;
    }
  }
  preview.addEventListener('close', () => {
    previewRequest = null;
    previewView.replaceChildren();
    previewDiff.textContent = '';
  });

  dispatch.addEventListener('click', () => {
    if (demo) return notify('切回实时模式，就可以分配本机任务。');
    byId('new-error').textContent = '';
    compose.showModal();
    brief.focus();
  });
  list.addEventListener('click', event => {
    const row = event.target.closest('[data-task]');
    if (row) openTask(tasks.find(task => task.id === row.dataset.task));
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (demo || writing) return;
    const briefText = brief.value.trim();
    const error = byId('new-error');
    if (!briefText || briefText.length > brief.maxLength) {
      error.textContent = '请填写任务目标，最多 ' + brief.maxLength + ' 字。';
      brief.focus();
      return;
    }
    writing = true;
    lockControls();
    error.textContent = '';
    try {
      if (!submission || submission.brief !== briefText) submission = {brief:briefText, id:crypto.randomUUID()};
      const { task } = await api('/api/tasks', { brief: briefText, requestId:submission.id });
      submission = null;
      remember(task);
      form.reset();
      if (compose.open) compose.close();
      if (!demo) openTask(task);
    } catch (err) {
      error.textContent = err instanceof TypeError ? '未收到服务响应。请先查看任务台确认是否已创建。' : err.message;
      void refresh();
    } finally {
      writing = false;
      lockControls();
    }
  });

  content.addEventListener('input', event => {
    const task = selectedTask();
    if (event.target.id === 'manual-result' && task && current(task)) drafts.set(key(task, current(task)), event.target.value);
    if (event.target.id === 'retry-note' && task && current(task)) drafts.set(key(task,current(task))+'/retry',event.target.value);
    if (event.target.id === 'reject-note' && task) drafts.set(task.id+'/reject', event.target.value);
  });
  content.addEventListener('click', async event => {
    const button = event.target.closest('[data-action]');
    const task = selectedTask();
    const step = task && current(task);
    if (!button || !task || demo) return;
    const action = button.dataset.action;
    if (action==='preview' && task.release) {
      await openPreview(task);
      return;
    }
    if (action==='live-office') {
      const url=new URL(location.href);
      url.searchParams.delete('task');
      url.hash='office';
      history.replaceState(null,'',url);
      location.reload();
      return;
    }
    if (['accept', 'reject', 'rollback', 'stop'].includes(action)) {
      if (writing) return;
      const errorBox=byId('action-error');
      const payload = action === 'stop' ? {} : candidate(task);
      if (action === 'reject') {
        const note = byId('reject-note');
        payload.feedback = note.value.trim();
        if (!payload.feedback || payload.feedback.length > note.maxLength) {
          errorBox.textContent = '请填写返工意见，最多 2000 字。';
          note.focus();
          return;
        }
      }
      errorBox.textContent = '';
      writing=true; lockControls();
      try {
        const response=await api(taskPath(task)+'/'+action,payload);
        if (action === 'reject') drafts.delete(task.id+'/reject');
        if (action === 'stop' || action === 'accept') {
          for (const key of drafts.keys()) if (key.startsWith(task.id+'/')) drafts.delete(key);
        }
        remember(response.task);
        if (action === 'rollback') notify('已回退到发布前的版本。');
        if (action === 'stop') notify('任务已停止。');
      } catch(err) {
        if(errorBox.isConnected) errorBox.textContent=err.message;
        void refresh();
      } finally { writing=false; lockControls(); openRequestedTask(); }
      return;
    }
    if (!step) return;
    if(action==='dot'){document.dispatchEvent(new Event('office-dot'));return;}
    if (action === 'copy') {
      try {
        await navigator.clipboard.writeText(step.prompt);
        notify('已复制交接文本。');
      } catch {
        const box = content.querySelector('[data-focus="prompt"]');
        if (box) {
          box.closest('details').open = true;
          box.focus();
          box.select();
          notify('已选中交接文本，可使用系统复制快捷键。');
        }
      }
      return;
    }
    if (writing) return;
    const errorBox = byId('action-error');
    const payload = { action: action === 'retry-fresh' ? 'retry' : action, stepId: step.id, agent: step.agent };
    if (action === 'retry-fresh') payload.fresh = true;
    if (payload.action === 'retry' && byId('retry-note')?.value.trim()) payload.feedback = byId('retry-note').value.trim();
    if (action === 'manual') {
      const input = byId('manual-result');
      payload.result = input.value.trim();
      if (!payload.result || payload.result.length > 16000) {
        errorBox.textContent = '请填写实际成果，最多 16000 字。';
        input.focus();
        return;
      }
    }
    writing = true;
    lockControls();
    errorBox.textContent = '';
    try {
      const response = await api('/api/tasks/' + encodeURIComponent(task.id) + '/step', payload);
      if (action === 'manual') drafts.delete(key(task, step));
      if (payload.action === 'retry') drafts.delete(key(task,step)+'/retry');
      remember(response.task);
    } catch (err) {
      const message = err instanceof TypeError ? '未收到服务响应，请查看步骤最新状态。' : err.message;
      if (errorBox.isConnected) errorBox.textContent = message;
      else notify(message);
      void refresh();
    } finally {
      writing = false;
      lockControls();
    }
  });
  renderList();
  void refresh();
  window.setInterval(() => { if (!document.hidden) void refresh(); }, 3000);
  window.setInterval(() => { if (!document.hidden && detail.open) showElapsed(); }, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  return {
    hasDraft() { return writing || !!brief.value.trim() || [...drafts.values()].some(v=>v.trim()); },
    openFromTray(id) {
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)) return;
      requestedTask = id.toLowerCase();
      if (demo) byId('live').click();
      openRequestedTask();
      if (requestedTask) void refresh();
    },
    setCapabilities(value) { caps = value || {}; renderDetail(); },
    setDemo(value) {
      if (demo === value) return;
      demo = value;
      ++revision;
      dispatch.setAttribute('aria-disabled', String(demo));
      if (demo) {
        if (compose.open) compose.close();
        if (detail.open) detail.close();
      }
      renderList();
      if (!demo) void refresh();
    },
    refresh,
  };
}
