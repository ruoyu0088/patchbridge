import { reactive } from './vue.js';

export const ui = reactive({
  toast: null,
  confirm: null,
  busy: false,
});

let toastTimer = null;
export function notify(message, type = 'info') {
  ui.toast = { message, type };
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    ui.toast = null;
  }, 3800);
}

export function confirmDialog(options) {
  return new Promise((resolve) => {
    ui.confirm = {
      title: options.title || '请确认',
      message: options.message || '',
      confirmText: options.confirmText || '确认',
      cancelText: options.cancelText || '取消',
      danger: Boolean(options.danger),
      checks: options.checks || null,
      resolve,
    };
  });
}

export function resolveConfirm(value) {
  if (!ui.confirm) return;
  const resolve = ui.confirm.resolve;
  ui.confirm = null;
  resolve(value);
}

export function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function shortDate(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19);
}

export function statusText(status) {
  return (
    {
      packed: '待 AI 回答',
      parsed: '已解析',
      applied: '已应用',
      reverted: '已撤回',
      abandoned: '已放弃',
      corrupt: '数据损坏',
    }[status] || status || '未知'
  );
}

export function hashText(value) {
  return (
    {
      ok: 'hash 一致',
      changed: 'hash 变化',
      missing: '文件缺失',
      new: '新增文件',
      unselected: '未选中',
    }[value] || value || ''
  );
}

export function applyText(value) {
  return (
    {
      ok: '可应用',
      conflict: '冲突',
      unsupported: '不支持',
    }[value] || value || '未检查'
  );
}

export function scopeText(value) {
  return (
    {
      ok: '范围内',
      outside: '工程外',
      excluded: '被 profile 排除',
    }[value] || value || ''
  );
}

export async function copyText(text, label = '内容') {
  try {
    await navigator.clipboard.writeText(text);
    notify(`${label}已复制到剪贴板`, 'success');
  } catch (err) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.focus();
    area.select();
    try {
      document.execCommand('copy');
      notify(`${label}已复制到剪贴板`, 'success');
    } catch (fallbackError) {
      notify('复制失败，请手工选择文本', 'error');
    } finally {
      area.remove();
    }
  }
}

export function diffLines(text) {
  if (!text) return [];
  const raw = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const lines = [];
  let oldNo = 0;
  let newNo = 0;
  for (const line of raw) {
    if (line.startsWith('@@')) {
      const match = line.match(/@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/);
      if (match) {
        oldNo = Number(match[1]);
        newNo = Number(match[2]);
      }
      lines.push({ type: 'hunk', text: line, oldNo: '', newNo: '' });
      continue;
    }
    if (
      line.startsWith('diff --git ') ||
      line.startsWith('index ') ||
      line.startsWith('new file mode ') ||
      line.startsWith('deleted file mode ') ||
      line.startsWith('--- ') ||
      line.startsWith('+++ ') ||
      line.startsWith('\\ No newline')
    ) {
      lines.push({ type: 'meta', text: line, oldNo: '', newNo: '' });
      continue;
    }
    if (line.startsWith('+')) {
      lines.push({ type: 'add', text: line, oldNo: '', newNo: newNo || '' });
      newNo += 1;
      continue;
    }
    if (line.startsWith('-')) {
      lines.push({ type: 'del', text: line, oldNo: oldNo || '', newNo: '' });
      oldNo += 1;
      continue;
    }
    if (line.startsWith(' ')) {
      lines.push({ type: 'ctx', text: line, oldNo: oldNo || '', newNo: newNo || '' });
      oldNo += 1;
      newNo += 1;
      continue;
    }
    if (line === '') continue;
    lines.push({ type: 'meta', text: line, oldNo: '', newNo: '' });
  }
  return lines;
}

export function buildTree(files) {
  const root = { name: '', path: '', type: 'dir', children: [], leaves: [] };
  const dirs = new Map([['', root]]);
  for (const file of files) {
    const parts = String(file.path).split('/');
    let parent = root;
    for (let i = 0; i < parts.length - 1; i += 1) {
      const path = parts.slice(0, i + 1).join('/');
      let dir = dirs.get(path);
      if (!dir) {
        dir = { name: parts[i], path, type: 'dir', children: [], leaves: [] };
        dirs.set(path, dir);
        parent.children.push(dir);
      }
      parent = dir;
    }
    parent.children.push({
      name: parts[parts.length - 1],
      path: file.path,
      type: 'file',
      size: file.size,
      children: [],
      leaves: [file.path],
    });
  }
  function finish(node) {
    if (node.type === 'file') {
      node.leaves = [node.path];
      return node.leaves;
    }
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.leaves = node.children.flatMap(finish);
    return node.leaves;
  }
  finish(root);
  return root.children;
}
