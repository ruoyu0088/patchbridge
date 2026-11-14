import { api, ApiError } from './api.js';
import {
  ui,
  notify,
  confirmDialog,
  resolveConfirm as closeConfirm,
  formatBytes,
  shortDate,
  statusText,
  hashText,
  applyText,
  scopeText,
  copyText,
  diffLines,
  buildTree,
} from './tools.js';
import {
  t,
  getLocale,
  installI18n,
  reloadWithLocale,
  applyDocumentLocale,
} from './i18n.js';

const Vue = window.Vue;

const DiffView = {
  name: 'DiffView',
  props: { content: { type: String, default: '' } },
  computed: {
    lines() {
      return diffLines(this.content);
    },
  },
  template: `
    <div class="diff-view">
      <div v-if="!lines.length" class="muted">{{ $t('没有可显示的 diff') }}</div>
      <div v-for="(line, idx) in lines" :key="idx" :class="['diff-line', 'diff-' + line.type]">
        <span class="diff-ln">{{ line.oldNo }}</span>
        <span class="diff-ln">{{ line.newNo }}</span>
        <span class="diff-code">{{ line.text || ' ' }}</span>
      </div>
    </div>
  `,
};

const SideDiff = {
  name: 'SideDiff',
  props: {
    rows: { type: Array, default: () => [] },
    context: { type: Number, default: 3 },
  },
  computed: {
    hunks() {
      const rows = this.rows || [];
      if (!rows.length) return [];
      const changed = [];
      rows.forEach((row, index) => {
        if (row.type !== 'equal') changed.push(index);
      });
      if (!changed.length) return [];
      const ranges = [];
      for (const index of changed) {
        const start = Math.max(0, index - this.context);
        const end = Math.min(rows.length, index + this.context + 1);
        const last = ranges[ranges.length - 1];
        if (last && start <= last.end) last.end = Math.max(last.end, end);
        else ranges.push({ start, end });
      }
      return ranges.map((range) => {
        const slice = rows.slice(range.start, range.end);
        const first = slice[0] || {};
        const oldStart = first.old_line || 1;
        const newStart = first.new_line || 1;
        const oldCount = slice.filter((row) => row.old_line).length;
        const newCount = slice.filter((row) => row.new_line).length;
        return {
          key: `${range.start}-${range.end}`,
          header: `@@ -${oldStart},${oldCount} +${newStart},${newCount} @@`,
          rows: slice,
        };
      });
    },
  },
  template: `
    <div class="side-diff">
      <div v-if="!hunks.length" class="muted pad-small">{{ $t('没有可显示的差异') }}</div>
      <div v-for="hunk in hunks" :key="hunk.key" class="side-hunk">
        <div class="side-hunk-head mono">{{ hunk.header }}</div>
        <table class="side-table">
          <tbody>
            <tr v-for="(row, idx) in hunk.rows" :key="idx" :class="'side-' + row.type">
              <td class="side-ln">{{ row.old_line || '' }}</td>
              <td class="side-text old"><span>{{ row.old_text || ' ' }}</span></td>
              <td class="side-ln">{{ row.new_line || '' }}</td>
              <td class="side-text new"><span>{{ row.new_text || ' ' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};

const FileTreeNode = {
  name: 'FileTreeNode',
  props: {
    node: { type: Object, required: true },
    selected: { type: Object, required: true },
  },
  data() {
    return { expanded: true };
  },
  computed: {
    isDir() {
      return this.node.type === 'dir';
    },
    checked() {
      if (!this.node.leaves.length) return false;
      return this.node.leaves.every((path) => Boolean(this.selected[path]));
    },
    partial() {
      if (!this.isDir) return false;
      const count = this.node.leaves.filter((path) => Boolean(this.selected[path])).length;
      return count > 0 && count < this.node.leaves.length;
    },
  },
  methods: {
    formatBytes,
    change(event) {
      this.$emit('toggle', this.node, event.target.checked);
    },
    forward(node, checked) {
      this.$emit('toggle', node, checked);
    },
  },
  template: `
    <div class="tree-node">
      <div class="tree-row">
        <button v-if="isDir" class="tree-caret" @click="expanded = !expanded" type="button">
          {{ expanded ? '▾' : '▸' }}
        </button>
        <span v-else class="tree-caret-space"></span>
        <input
          type="checkbox"
          :checked="checked"
          :indeterminate="partial"
          @change="change"
        />
        <span
          :class="['tree-name', isDir ? 'tree-dir' : '']"
          @click="isDir ? (expanded = !expanded) : null"
        >{{ node.name }}{{ isDir ? '/' : '' }}</span>
        <span v-if="!isDir" class="tree-size">{{ formatBytes(node.size) }}</span>
      </div>
      <div v-if="isDir && expanded" class="tree-children">
        <file-tree-node
          v-for="child in node.children"
          :key="child.path"
          :node="child"
          :selected="selected"
          @toggle="forward"
        />
      </div>
    </div>
  `,
};

const ProjectsPage = {
  name: 'ProjectsPage',
  data() {
    return { projects: [], loading: true, error: '', editor: null, saving: false };
  },
  mounted() {
    this.load();
  },
  methods: {
    formatBytes,
    async load() {
      this.loading = true;
      try {
        const data = await api.get('/api/projects');
        this.projects = data.projects || [];
        this.error = '';
      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
    template() {
      return `# PatchBridge profile v1
name: ${t('新工程')}
root: C:\\path\\to\\your\\project
mode: exclude

[rules]
.git/
node_modules/
dist/
*.log
`;
    },
    create() {
      this.editor = { mode: 'create', id: '', raw: this.template(), error: '' };
    },
    edit(project) {
      this.editor = { mode: 'edit', id: project.id, raw: project.raw || '', error: '' };
    },
    async save() {
      if (!this.editor) return;
      this.saving = true;
      this.editor.error = '';
      try {
        if (this.editor.mode === 'create') {
          await api.post('/api/projects', { raw: this.editor.raw });
        } else {
          await api.put(`/api/projects/${encodeURIComponent(this.editor.id)}`, {
            raw: this.editor.raw,
          });
        }
        this.editor = null;
        notify(t('profile 已保存'), 'success');
        await this.load();
        if (this.$root && typeof this.$root.loadSidebar === 'function') {
          this.$root.loadSidebar();
        }
      } catch (err) {
        this.editor.error = err.message;
      } finally {
        this.saving = false;
      }
    },
    async remove(project) {
      const yes = await confirmDialog({
        title: t('删除工程'),
        message: t('确定删除工程「{name}」的 profile 吗？历史会话会保留。', {
          name: project.name,
        }),
        confirmText: t('删除'),
        danger: true,
      });
      if (!yes) return;
      try {
        await api.delete(`/api/projects/${encodeURIComponent(project.id)}`);
        notify(t('工程已删除'), 'success');
        await this.load();
        if (this.$root && typeof this.$root.loadSidebar === 'function') {
          this.$root.loadSidebar();
        }
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    open(project) {
      if (!project.root_status || !project.root_status.accessible) return;
      location.hash = `#/project/${encodeURIComponent(project.id)}`;
    },
  },
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>{{ $t('工程') }}</h1>
          <p class="muted">{{ $t('每个工程由一个 profile 文件定义根目录和 gitignore 规则。') }}</p>
        </div>
        <button class="btn primary" @click="create">{{ $t('新建工程') }}</button>
      </div>

      <div v-if="error" class="alert error">{{ error }}</div>
      <div v-if="loading" class="empty">{{ $t('加载中…') }}</div>
      <div v-else-if="!projects.length" class="empty">
        {{ $t('还没有工程。点击“新建工程”创建第一个 profile。') }}
      </div>
      <div v-else class="project-grid">
        <article v-for="project in projects" :key="project.id" class="project-card">
          <div class="project-card-head">
            <h2>{{ project.name }}</h2>
            <span v-if="project.root_status && project.root_status.accessible" class="badge ok">{{ $t('可用') }}</span>
            <span v-else class="badge bad">{{ $t('不可用') }}</span>
          </div>
          <div class="mono path-line">{{ project.root || $t('（未设置根目录）') }}</div>
          <div class="project-meta">
            <span>{{ $t('模式：{mode}', { mode: project.mode === 'include' ? $t('包含白名单') : $t('排除') }) }}</span>
            <span>{{ $t('规则：{count}', { count: (project.rules || []).length }) }}</span>
          </div>
          <div v-if="project.root_status && project.root_status.error" class="alert error small">
            {{ project.root_status.error }}{{ $t('，禁止打包。') }}
          </div>
          <div v-if="project.error" class="alert error small">{{ project.error }}</div>
          <div v-if="project.warnings && project.warnings.length" class="warnings small">
            <div v-for="(warning, idx) in project.warnings" :key="idx">• {{ warning }}</div>
          </div>
          <div class="card-actions">
            <button class="btn primary" :disabled="!project.root_status || !project.root_status.accessible" @click="open(project)">
              {{ $t('打开') }}
            </button>
            <button class="btn" @click="edit(project)">{{ $t('编辑 profile') }}</button>
            <button class="btn danger-text" @click="remove(project)">{{ $t('删除') }}</button>
          </div>
        </article>
      </div>

      <div v-if="editor" class="modal-backdrop" @click.self="editor = null">
        <div class="modal wide">
          <div class="modal-head">
            <h2>{{ editor.mode === 'create' ? $t('新建 profile') : $t('编辑 profile') }}</h2>
            <button class="icon-btn" @click="editor = null">×</button>
          </div>
          <p class="muted">
            {{ $t('纯文本 profile：root 必须是绝对路径；mode 为 exclude 或 include； [rules] 使用 gitignore 语法，支持 ! 取反。') }}
          </p>
          <textarea v-model="editor.raw" class="code-editor profile-editor" spellcheck="false"></textarea>
          <div v-if="editor.error" class="alert error">{{ editor.error }}</div>
          <div class="modal-actions">
            <button class="btn" @click="editor = null">{{ $t('取消') }}</button>
            <button class="btn primary" :disabled="saving" @click="save">{{ saving ? $t('保存中…') : $t('保存') }}</button>
          </div>
        </div>
      </div>
    </div>
  `,
};

const ProjectPage = {
  name: 'ProjectPage',
  components: { FileTreeNode },
  props: { projectId: { type: String, required: true } },
  data() {
    return {
      ui,
      project: null,
      files: [],
      summary: null,
      binaryFiles: [],
      binaryTruncated: false,
      loading: true,
      error: '',
      query: '',
      selected: {},
      requirement: '',
      packMode: 'python',
      packing: false,
      packResult: null,
      bundleText: '',
      bundlePreviewOpen: false,
      bundleLoading: false,
      autoSending: false,
      profileEditor: null,
    };
  },
  computed: {
    filteredFiles() {
      const q = this.query.trim().toLowerCase();
      if (!q) return this.files;
      return this.files.filter((file) => file.path.toLowerCase().includes(q));
    },
    tree() {
      return buildTree(this.filteredFiles);
    },
    selectedPaths() {
      return Object.keys(this.selected).filter((path) => this.selected[path]);
    },
    selectedBytes() {
      const map = new Map(this.files.map((file) => [file.path, file.size]));
      return this.selectedPaths.reduce((sum, path) => sum + (map.get(path) || 0), 0);
    },
    selectedCount() {
      return this.selectedPaths.length;
    },
    accessible() {
      return Boolean(this.project && this.project.root_status && this.project.root_status.accessible);
    },
    binaryCount() {
      return (
        (this.summary && this.summary.skipped && this.summary.skipped.binary) ||
        this.binaryFiles.length
      );
    },
  },
  mounted() {
    this.load();
  },
  watch: {
    projectId() {
      this.load();
    },
  },
  created() {
    this.selectionSaveTimer = null;
    this.selectionSaveChain = Promise.resolve();
    this.pendingSelectionProjectId = null;
  },
  beforeUnmount() {
    this.flushSelectionSave();
  },
  methods: {
    formatBytes,
    async load() {
      this.flushSelectionSave();
      this.loading = true;
      this.error = '';
      this.selected = {};
      this.packResult = null;
      this.files = [];
      this.summary = null;
      this.binaryFiles = [];
      this.binaryTruncated = false;
      this.query = '';
      this.requirement = '';
      this.bundleText = '';
      this.bundlePreviewOpen = false;
      try {
        const projectData = await api.get(`/api/projects/${encodeURIComponent(this.projectId)}`);
        this.project = projectData.project;
        if (!this.project.root_status.accessible) {
          this.loading = false;
          return;
        }
        const [treeData, selectionData] = await Promise.all([
          api.get(`/api/projects/${encodeURIComponent(this.projectId)}/tree`),
          api
            .get(`/api/projects/${encodeURIComponent(this.projectId)}/selection`)
            .catch(() => ({ files: [] })),
        ]);
        this.files = treeData.files || [];
        this.summary = treeData.summary || null;
        this.binaryFiles = (treeData.skipped_files && treeData.skipped_files.binary) || [];
        this.binaryTruncated = Boolean(
          treeData.skipped_files && treeData.skipped_files.binary_truncated,
        );
        this.selected = this.selectedFromSaved(selectionData.files);
      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
    toggleNode(node, checked) {
      for (const path of node.leaves || []) {
        this.selected[path] = checked;
      }
      this.scheduleSelectionSave();
    },
    fullPath(rel) {
      const root = (this.project && this.project.root) || '';
      const separator = root.includes('\\') ? '\\' : '/';
      return root.replace(/[\\/]+$/, '') + separator + rel.split('/').join(separator);
    },
    async copyFilePath(rel) {
      await copyText(this.fullPath(rel), t('文件绝对路径'));
    },
    dirState(node) {
      if (!node.leaves || !node.leaves.length) return 'none';
      const count = node.leaves.filter((path) => this.selected[path]).length;
      if (count === 0) return 'none';
      if (count === node.leaves.length) return 'all';
      return 'some';
    },
    selectAll() {
      for (const file of this.filteredFiles) this.selected[file.path] = true;
      this.scheduleSelectionSave();
    },
    clearAll() {
      this.selected = {};
      this.scheduleSelectionSave();
    },
    selectedFromSaved(savedPaths) {
      const available = new Set(this.files.map((file) => file.path));
      const result = {};
      for (const path of savedPaths || []) {
        if (available.has(path)) result[path] = true;
      }
      return result;
    },
    scheduleSelectionSave() {
      this.pendingSelectionProjectId = this.projectId;
      if (this.selectionSaveTimer) clearTimeout(this.selectionSaveTimer);
      this.selectionSaveTimer = setTimeout(() => {
        this.selectionSaveTimer = null;
        this.persistSelection();
      }, 400);
    },
    cancelScheduledSelectionSave() {
      if (this.selectionSaveTimer) {
        clearTimeout(this.selectionSaveTimer);
        this.selectionSaveTimer = null;
      }
    },
    flushSelectionSave() {
      if (!this.selectionSaveTimer) return;
      this.cancelScheduledSelectionSave();
      this.persistSelection();
    },
    persistSelection() {
      const projectId = this.pendingSelectionProjectId || this.projectId;
      this.pendingSelectionProjectId = null;
      if (!projectId || !this.project || !this.accessible) return;
      const files = [...this.selectedPaths];
      this.selectionSaveChain = this.selectionSaveChain
        .catch(() => {})
        .then(() => api.put(`/api/projects/${encodeURIComponent(projectId)}/selection`, { files }))
        .catch((err) => {
          notify(t('保存文件选择失败：{error}', { error: err.message }), 'error');
        });
    },
    async pack() {
      if (!this.accessible) return;
      if (!this.requirement.trim()) {
        notify(t('请先输入需求'), 'error');
        return;
      }
      if (!this.selectedPaths.length) {
        notify(t('请至少勾选一个文件'), 'error');
        return;
      }
      this.packing = true;
      try {
        this.packResult = await api.post(
          `/api/projects/${encodeURIComponent(this.projectId)}/pack`,
          { requirement: this.requirement, files: this.selectedPaths, mode: this.packMode },
        );
        this.bundleText = '';
        this.bundlePreviewOpen = false;
        notify(t('打包完成。现在可以把完整文本或文件路径交给 Web AI。'), 'success');
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.packing = false;
      }
    },
    async autoDeepseek() {
      if (!this.packResult) return;
      if (this.ui.auto.running) {
        notify(t('已有自动输入任务在运行'), 'error');
        return;
      }
      this.autoSending = true;
      try {
        await api.post(
          `/api/sessions/${encodeURIComponent(this.packResult.session_id)}/auto-deepseek`,
        );
        this.ui.auto.running = true;
        this.ui.auto.sessionId = this.packResult.session_id;
        this.ui.auto.message = t('正在启动自动化…');
        notify(t('已启动自动输入，请不要操作键盘和鼠标'), 'info');
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.autoSending = false;
      }
    },
    openProfileEditor() {
      const raw = (this.project && this.project.raw) || '';
      this.profileEditor = { raw, error: '', saving: false };
    },
    async refreshAfterProfileSave() {
      try {
        const projectData = await api.get(
          `/api/projects/${encodeURIComponent(this.projectId)}`,
        );
        this.project = projectData.project;
        if (!this.project.root_status.accessible) {
          this.files = [];
          this.summary = null;
          this.binaryFiles = [];
          this.binaryTruncated = false;
          this.error = this.project.root_status.error || t('根目录不可访问');
          return;
        }
        const treeData = await api.get(
          `/api/projects/${encodeURIComponent(this.projectId)}/tree`,
        );
        this.files = treeData.files || [];
        this.summary = treeData.summary || null;
        this.binaryFiles =
          (treeData.skipped_files && treeData.skipped_files.binary) || [];
        this.binaryTruncated = Boolean(
          treeData.skipped_files && treeData.skipped_files.binary_truncated,
        );
        const available = new Set(this.files.map((file) => file.path));
        const nextSelected = {};
        for (const path of Object.keys(this.selected)) {
          if (available.has(path) && this.selected[path]) {
            nextSelected[path] = true;
          }
        }
        this.selected = nextSelected;
        this.error = '';
      } catch (err) {
        this.error = err.message;
      }
    },
    async saveProfileEditor() {
      if (!this.profileEditor) return;
      this.profileEditor.saving = true;
      this.profileEditor.error = '';
      try {
        await api.put(`/api/projects/${encodeURIComponent(this.projectId)}`, {
          raw: this.profileEditor.raw,
        });
        notify(t('工程定义已保存，文件树已刷新'), 'success');
        this.profileEditor = null;
        await this.refreshAfterProfileSave();
        if (this.$root && typeof this.$root.loadSidebar === 'function') {
          this.$root.loadSidebar();
        }
      } catch (err) {
        if (this.profileEditor) {
          this.profileEditor.error = err.message;
        }
      } finally {
        if (this.profileEditor) {
          this.profileEditor.saving = false;
        }
      }
    },
    async copyBundleText() {
      try {
        const text = this.bundleText || (await api.text(`/api/sessions/${this.packResult.session_id}/bundle`));
        this.bundleText = text;
        await copyText(text, t('打包全文'));
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async copyBundlePath() {
      if (!this.packResult || !this.packResult.bundle_path) return;
      await copyText(this.packResult.bundle_path, t('打包文件路径'));
    },
    async toggleBundlePreview() {
      if (!this.packResult) return;
      this.bundlePreviewOpen = !this.bundlePreviewOpen;
      if (this.bundlePreviewOpen && !this.bundleText) {
        this.bundleLoading = true;
        try {
          this.bundleText = await api.text(`/api/sessions/${this.packResult.session_id}/bundle`);
        } catch (err) {
          notify(err.message, 'error');
        } finally {
          this.bundleLoading = false;
        }
      }
    },
    downloadBundle() {
      if (!this.packResult) return;
      const link = document.createElement('a');
      link.href = `/api/sessions/${this.packResult.session_id}/bundle`;
      link.download = `${this.packResult.session_id}-bundle.txt`;
      link.click();
    },
    openSession() {
      if (this.packResult) {
        location.hash = `#/session/${this.packResult.session_id}`;
      }
    },
    back() {
      location.hash = '#/projects';
    },
  },
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <button class="btn link" @click="back">{{ $t('← 工程列表') }}</button>
          <h1>{{ project ? project.name : $t('工程') }}</h1>
          <div v-if="project" class="mono path-line">{{ project.root }}</div>
        </div>
        <div v-if="summary" class="summary-pills">
          <span class="pill">{{ $t('{count} 个可选文件', { count: summary.count }) }}</span>
          <span class="pill">{{ formatBytes(summary.bytes) }}</span>
          <span v-if="summary.skipped.large" class="pill muted">{{ $t('大文件 {count}', { count: summary.skipped.large }) }}</span>
          <span v-if="summary.skipped.binary" class="pill muted">{{ $t('二进制 {count}', { count: summary.skipped.binary }) }}</span>
        </div>
      </div>

      <div v-if="loading" class="empty">{{ $t('加载文件树…') }}</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <div v-else-if="!accessible" class="alert error">
        {{ $t('根目录不可访问，禁止打包。请编辑 profile 修正 root。') }}
      </div>
      <div v-else class="workspace-grid">
        <section class="panel tree-panel">
          <div class="panel-head">
            <h2>{{ $t('文件树') }}</h2>
            <div class="small-actions">
              <button class="btn tiny" @click="openProfileEditor">{{ $t('编辑工程定义') }}</button>
              <button class="btn tiny" @click="selectAll">{{ $t('全选当前') }}</button>
              <button class="btn tiny" @click="clearAll">{{ $t('清空') }}</button>
            </div>
          </div>
          <input v-model="query" class="search-input" :placeholder="$t('按路径搜索…')" />
          <div class="tree-scroll">
            <div v-if="!filteredFiles.length" class="muted pad">{{ $t('没有匹配的文件') }}</div>
            <file-tree-node
              v-for="node in tree"
              :key="node.path"
              :node="node"
              :selected="selected"
              @toggle="toggleNode"
            />
          </div>
          <div class="selection-bar">
            {{ $t('已选') }} <strong>{{ selectedCount }}</strong> {{ $t('个文件，共 {size}', { size: formatBytes(selectedBytes) }) }}
          </div>
        </section>

        <section class="panel compose-panel">
          <div
            v-if="profileEditor"
            class="inline-profile-editor"
            style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--line);"
          >
            <div class="panel-head">
              <h2>{{ $t('编辑工程定义') }}</h2>
              <div class="small-actions">
                <button class="btn tiny" @click="profileEditor = null">{{ $t('关闭') }}</button>
              </div>
            </div>
            <p class="muted small">
              {{ $t('纯文本 profile：root 必须是绝对路径；mode 为 exclude 或 include； [rules] 使用 gitignore 语法，支持 ! 取反。保存后文件树会立即刷新。') }}
            </p>
            <textarea
              v-model="profileEditor.raw"
              class="code-editor profile-editor"
              spellcheck="false"
            ></textarea>
            <div v-if="profileEditor.error" class="alert error small">{{ profileEditor.error }}</div>
            <div class="button-row" style="margin-top: 10px;">
              <button
                class="btn primary"
                :disabled="profileEditor.saving"
                @click="saveProfileEditor"
              >{{ profileEditor.saving ? $t('保存中…') : $t('保存并刷新文件树') }}</button>
              <button class="btn" @click="profileEditor = null">{{ $t('取消') }}</button>
            </div>
          </div>
          <div class="panel-head"><h2>{{ $t('需求与打包') }}</h2></div>
          <label class="field-label">{{ $t('回答格式') }}</label>
          <div class="mode-picker">
            <label class="mode-option" :class="{ active: packMode === 'python' }">
              <input v-model="packMode" type="radio" value="python" />
              <span>
                <strong>{{ $t('Python 脚本') }}</strong>
                <small>{{ $t('AI 调用补丁 API，不写 diff、不算行号；推荐') }}</small>
              </span>
            </label>
            <label class="mode-option" :class="{ active: packMode === 'diff' }">
              <input v-model="packMode" type="radio" value="diff" />
              <span>
                <strong>Unified diff</strong>
                <small>{{ $t('传统格式，兼容旧会话和外部工具') }}</small>
              </span>
            </label>
          </div>
          <label class="field-label">{{ $t('修改需求') }}</label>
          <textarea
            v-model="requirement"
            class="requirement-editor"
            :placeholder="$t('说明要改什么、期望的行为、限制和验收标准…')"
          ></textarea>
          <div class="compose-actions">
            <button class="btn primary" :disabled="packing" @click="pack">
              {{ packing ? $t('打包中…') : $t('生成打包文本') }}
            </button>
            <span class="muted">{{ $t('打包前会记录每个文件的 sha256 快照。') }}</span>
          </div>

          <div v-if="packResult" class="bundle-result">
            <div class="bundle-result-head">
              <h3>{{ $t('打包完成') }}</h3>
              <span class="badge ok">{{ $t('{count} 个文件', { count: packResult.file_count }) }}</span>
              <span class="pill">{{ packResult.mode === 'python' ? $t('Python 脚本模式') : $t('diff 模式') }}</span>
              <span class="pill">{{ formatBytes(packResult.bundle_size) }}</span>
              <span class="pill">{{ $t('约 {count} tokens', { count: packResult.token_estimate }) }}</span>
            </div>
            <p class="muted">
              {{ $t('两种方式任选其一交给 Web AI：复制完整文本，或复制下面的文件路径后在本地打开/上传文件。') }}
            </p>
            <div class="path-copy-row">
              <code class="mono path-box">{{ packResult.bundle_path }}</code>
              <button class="btn" @click="copyBundlePath">{{ $t('复制文件路径') }}</button>
            </div>
            <div class="button-row">
              <button class="btn primary" @click="copyBundleText">{{ $t('复制完整文本') }}</button>
              <button class="btn" @click="downloadBundle">{{ $t('下载文本文件') }}</button>
              <button class="btn" @click="toggleBundlePreview">
                {{ bundlePreviewOpen ? $t('收起预览') : $t('预览文本') }}
              </button>
              <button class="btn accent" @click="openSession">{{ $t('打开审阅页 →') }}</button>
            </div>
            <div class="button-row auto-deepseek-row">
              <button
                class="btn primary"
                :disabled="autoSending || ui.auto.running"
                @click="autoDeepseek"
              >
                {{ autoSending ? $t('启动中…') : $t('自动输入到 DeepSeek') }}
              </button>
              <span class="muted small">
                {{ $t('将自动粘贴需求并把 bundle.txt 作为附件上传，不会自动提交；完成后请人工确认后手动发送。') }}
              </span>
            </div>
            <div v-if="bundlePreviewOpen" class="bundle-preview">
              <div v-if="bundleLoading" class="muted">{{ $t('读取中…') }}</div>
              <pre v-else>{{ bundleText }}</pre>
            </div>
            <p class="hint">
              {{ $t('打包文本保存于会话') }} <code>{{ packResult.session_id }}</code>{{ $t('，之后可在历史中重新载入。') }}
            </p>
          </div>
        </section>
      </div>

      <section v-if="binaryFiles.length" class="panel skipped-panel">
        <details open>
          <summary>
            <strong>{{ $t('已自动排除的二进制文件') }}</strong>
            <span class="badge warning">{{ binaryCount }}</span>
            <span class="muted">{{ $t('点击路径可复制绝对路径；这些文件不会出现在文件树中。') }}</span>
          </summary>
          <p class="hint">
            {{ $t('如果其中某个文件其实是文本，请检查文件编码或内容；PatchBridge 只把无法可靠识别为文本的文件归为二进制。') }}
          </p>
          <div class="binary-list">
            <button
              v-for="path in binaryFiles"
              :key="path"
              class="binary-row"
              :title="fullPath(path)"
              @click="copyFilePath(path)"
            >
              <code>{{ path }}</code>
              <span>{{ $t('复制绝对路径') }}</span>
            </button>
          </div>
          <p v-if="binaryTruncated" class="hint">
            {{ $t('二进制文件超过显示上限，这里只列出前 {shown} 个，共 {total} 个。', { shown: binaryFiles.length, total: binaryCount }) }}
          </p>
        </details>
      </section>
    </div>
  `,
};

const SessionPage = {
  name: 'SessionPage',
  components: { DiffView, SideDiff },
  props: { sessionId: { type: String, required: true } },
  data() {
    return {
      details: null,
      loading: true,
      error: '',
      tab: 'review',
      answerText: '',
      statuses: {},
      selected: {},
      openPatches: {},
      answerDraft: '',
      commitDraft: '',
      editingCommit: false,
      editingPatchId: null,
      patchDraft: '',
      alignUndo: null,
      alignAdded: true,
      aligningPatchId: null,
      bundleText: '',
      bundleLoading: false,
      disk: null,
      diskLoading: false,
      busy: false,
      confirmApply: null,
      hashConfirmChecked: {},
      applyResult: null,
      reverting: false,
      merging: false,
      scriptText: '',
      scriptRunning: false,
      diffContext: 3,
      contextInitialized: false,
      scriptScrollFrame: null,
    };
  },
  computed: {
    meta() {
      return (this.details && this.details.meta) || {};
    },
    parsed() {
      return (this.details && this.details.parsed) || null;
    },
    patches() {
      return (this.details && this.details.patches) || [];
    },
    events() {
      return (this.details && this.details.events) || [];
    },
    status() {
      return (this.details && this.details.status) || 'packed';
    },
    archived() {
      return Boolean(this.details && this.details.archived);
    },
    patchLocked() {
      return Boolean(this.details && this.details.patch_locked);
    },
    hasUnrevertedApply() {
      return Boolean(this.details && this.details.has_unreverted_apply);
    },
    appliedPatchIds() {
      const ids = new Set();
      for (const event of this.events) {
        if (event.type === 'apply') {
          for (const id of event.data.patch_ids || []) ids.add(id);
        }
      }
      return ids;
    },
    selectedIds() {
      return Object.keys(this.selected).filter((id) => this.selected[id]);
    },
    warnings() {
      return (this.parsed && this.parsed.warnings) || [];
    },
    requirement() {
      return (this.details && this.details.requirement) || '';
    },
    bundlePath() {
      return (this.details && this.details.bundle_path) || '';
    },
    archivePath() {
      return (this.details && this.details.archive_path) || '';
    },
    editorGutterText() {
      const count = this.patchDraft ? this.patchDraft.split('\n').length : 1;
      return Array.from({ length: count }, (_, index) => index + 1).join('\n');
    },
    mode() {
      return (this.details && this.details.meta && this.details.meta.mode) || 'diff';
    },
    pythonMode() {
      return this.mode === 'python';
    },
    scriptReport() {
      return (
        (this.details && this.details.script && this.details.script.report) ||
        (this.parsed && this.parsed.script_result) ||
        null
      );
    },
    scriptSource() {
      return (
        (this.details && this.details.script && this.details.script.source) ||
        (this.parsed && this.parsed.script) ||
        ''
      );
    },
    scriptLineNumbers() {
      const count = this.scriptText ? this.scriptText.split('\n').length : 1;
      return Array.from({ length: count }, (_, index) => index + 1);
    },
    duplicateGroups() {
      const pending = this.patches.filter((patch) => !this.appliedPatchIds.has(patch.id));
      const map = new Map();
      for (const patch of pending) {
        const key = patch.path;
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(patch);
      }
      const groups = [];
      for (const [path, list] of map) {
        if (list.length > 1) groups.push({ path, patches: list });
      }
      return groups;
    },
  },
  mounted() {
    this.load();
  },
  beforeUnmount() {
    if (this.scriptScrollFrame) {
      cancelAnimationFrame(this.scriptScrollFrame);
      this.scriptScrollFrame = null;
    }
  },
  watch: {
    sessionId() {
      this.load();
    },
  },
  methods: {
    formatBytes,
    shortDate,
    statusText,
    hashText,
    applyText,
    scopeText,
    async load() {
      this.loading = true;
      this.error = '';
      this.statuses = {};
      this.bundleText = '';
      this.disk = null;
      this.applyResult = null;
      this.confirmApply = null;
      this.editingPatchId = null;
      this.editingCommit = false;
      this.alignUndo = null;
      this.aligningPatchId = null;
      try {
        this.details = await api.get(`/api/sessions/${encodeURIComponent(this.sessionId)}`);
        this.answerText = this.details.answer || '';
        this.scriptText = this.scriptSource || '';
        if (!this.contextInitialized) {
          this.contextInitialized = true;
          try {
            const settingsData = await api.get('/api/settings');
            const configured = Number(settingsData.settings && settingsData.settings.diff_context_lines);
            if (Number.isFinite(configured)) {
              this.diffContext = Math.max(0, Math.min(50, configured));
            }
          } catch (err) {
            /* 设置读取失败不影响审阅，保留默认 3 行 */
          }
        }
        this.commitDraft = (this.details.parsed && this.details.parsed.commit_message) || '';
        this.selected = {};
        for (const patch of this.patches) {
          if (!this.appliedPatchIds.has(patch.id)) this.selected[patch.id] = true;
          if (this.openPatches[patch.id] === undefined) {
            this.openPatches[patch.id] = true;
          }
        }
        if (this.parsed && this.patches.length) {
          const pending = this.patches
            .filter((patch) => !this.appliedPatchIds.has(patch.id))
            .map((patch) => patch.id);
          if (pending.length) await this.preview(false, pending);
          else this.statuses = {};
        }
      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
    async preview(persist = false, patchIds = null) {
      if (!this.patches.length) return null;
      const ids = patchIds === null ? null : patchIds;
      if (Array.isArray(ids) && !ids.length) {
        this.statuses = {};
        return null;
      }
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/dry-run`, {
          patch_ids: ids,
          persist,
        });
        const map = {};
        for (const item of data.results || []) map[item.patch_id] = item;
        this.statuses = map;
        return data;
      } catch (err) {
        if (persist) notify(err.message, 'error');
        return null;
      }
    },
    async dryAll() {
      const pending = this.patches
        .filter((patch) => !this.appliedPatchIds.has(patch.id))
        .map((patch) => patch.id);
      if (!pending.length) {
        notify(t('没有待应用的补丁'), 'info');
        return;
      }
      const data = await this.preview(true, pending);
      if (data) {
        notify(
          data.ok
            ? t('全部补丁通过 dry-run')
            : t('有 {count} 个补丁存在冲突', { count: data.conflicts }),
          data.ok ? 'success' : 'error',
        );
      }
    },
    async dryOne(patch) {
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/dry-run`, {
          patch_ids: [patch.id],
          persist: true,
        });
        for (const item of data.results || []) this.statuses[item.patch_id] = item;
        notify(
          data.ok
            ? t('{path} 可应用', { path: patch.path })
            : t('{path} 无法应用', { path: patch.path }),
          data.ok ? 'success' : 'error',
        );
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    statusFor(patch) {
      return this.statuses[patch.id] || null;
    },
    displayPatch(patch) {
      const status = this.statusFor(patch);
      if (status && status.final_patch) return status.final_patch;
      return patch.content;
    },
    hashState(patch) {
      const status = this.statusFor(patch);
      if (status) return status.hash_status;
      return patch.new_file ? 'new' : 'ok';
    },
    applyState(patch) {
      const status = this.statusFor(patch);
      return status ? status.apply_status : 'pending';
    },
    toggleAll() {
      const allSelected = this.patches
        .filter((patch) => !this.appliedPatchIds.has(patch.id))
        .every((patch) => this.selected[patch.id]);
      for (const patch of this.patches) {
        if (!this.appliedPatchIds.has(patch.id)) this.selected[patch.id] = !allSelected;
      }
    },
    isApplied(patch) {
      return this.appliedPatchIds.has(patch.id);
    },
    async mergeDuplicates() {
      const groups = this.duplicateGroups || [];
      if (!groups.length) return;
      const yes = await confirmDialog({
        title: t('合并同文件补丁'),
        message: t('将把 {count} 个文件的多条 diff 合并成一条，并用合并结果替换原有补丁。\n如果多条 diff 修改了原文件的同一区域，会保留原样并提示。\n\n确认开始合并吗？', {
          count: groups.length,
        }),
        confirmText: t('开始合并'),
      });
      if (!yes) return;
      this.merging = true;
      const results = [];
      try {
        for (const group of groups) {
          const ids = group.patches.map((patch) => patch.id);
          try {
            const data = await api.post(
              `/api/sessions/${this.sessionId}/patches/merge`,
              { patch_ids: ids },
            );
            results.push({ path: group.path, ok: true, added: data.added, removed: data.removed });
          } catch (err) {
            results.push({ path: group.path, ok: false, message: err.message });
          }
        }
      } finally {
        this.merging = false;
      }
      const okCount = results.filter((item) => item.ok).length;
      const failures = results.filter((item) => !item.ok);
      if (!failures.length) {
        notify(t('已合并 {count} 组同文件 diff', { count: okCount }), 'success');
      } else if (okCount === 0) {
        notify(
          t('全部 {count} 组未合并：{paths}', {
            count: failures.length,
            paths: failures.map((item) => item.path).join('、'),
          }),
          'error',
        );
      } else {
        notify(
          t('已合并 {ok} 组，{failed} 组未合并：{details}', {
            ok: okCount,
            failed: failures.length,
            details: failures.map((item) => `${item.path}（${item.message}）`).join('；'),
          }),
          'info',
        );
      }
      await this.load();
    },
    async applySelected() {
      if (!this.selectedIds.length) {
        notify(t('请至少勾选一个补丁'), 'error');
        return;
      }
      const changed = [];
      for (const id of this.selectedIds) {
        const status = this.statuses[id];
        if (status && status.hash_status === 'changed') changed.push(status.path);
      }
      if (changed.length) {
        this.hashConfirmChecked = {};
        this.confirmApply = { ids: [...this.selectedIds], paths: changed };
        return;
      }
      await this.doApply(this.selectedIds, []);
    },
    async doApply(ids, confirmed) {
      this.busy = true;
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/apply`, {
          patch_ids: ids,
          confirm_hash_changes: confirmed,
        });
        this.applyResult = data.apply;
        this.confirmApply = null;
        notify(t('补丁已应用，备份已写入'), 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'hash_changed') {
          this.confirmApply = { ids, paths: (err.details && err.details.paths) || [] };
          this.hashConfirmChecked = {};
          notify(t('有文件 hash 变化，需要逐项确认'), 'error');
        } else {
          notify(err.message, 'error');
          await this.preview(true, ids);
        }
      } finally {
        this.busy = false;
      }
    },
    confirmHashApply() {
      if (!this.confirmApply) return;
      if (this.confirmApply.paths.some((path) => !this.hashConfirmChecked[path])) {
        notify(t('请确认所有 hash 变化的文件'), 'error');
        return;
      }
      this.doApply(this.confirmApply.ids, this.confirmApply.paths);
    },
    async revert() {
      const yes = await confirmDialog({
        title: t('撤回最近一次应用'),
        message: t('撤回会按备份恢复本批次修改过的文件，并删除新增文件。是否继续？'),
        confirmText: t('撤回'),
        danger: true,
      });
      if (!yes) return;
      await this.doRevert(false);
    },
    async doRevert(confirmChanges) {
      this.reverting = true;
      try {
        await api.post(`/api/sessions/${this.sessionId}/revert`, {
          confirm_hash_changes: confirmChanges,
        });
        notify(t('已撤回最近一次应用'), 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'revert_hash_changed') {
          const paths = (err.details && err.details.paths) || [];
          const yes = await confirmDialog({
            title: t('文件在应用后又被改过'),
            message: t('以下文件与“应用后”不一致：\n{paths}\n\n确认仍按备份恢复吗？这会覆盖这些外部修改。', {
              paths: paths.join('\n'),
            }),
            confirmText: t('仍然撤回'),
            danger: true,
          });
          if (yes) await this.doRevert(true);
        } else {
          notify(err.message, 'error');
        }
      } finally {
        this.reverting = false;
      }
    },
    diagnosticsFor(patch) {
      const status = this.statusFor(patch);
      return status && status.diagnostics ? status.diagnostics : null;
    },
    mismatchFor(patch) {
      const diagnostics = this.diagnosticsFor(patch);
      return diagnostics ? diagnostics.first_mismatch : null;
    },
    patchRowClass(patch, row, index) {
      const mismatch = this.mismatchFor(patch);
      return {
        'compare-add': row.tag === '+',
        'compare-del': row.tag === '-',
        'compare-mismatch': Boolean(mismatch && mismatch.patch_row_index === index),
      };
    },
    fileRowClass(patch, row) {
      const mismatch = this.mismatchFor(patch);
      return {
        'compare-mismatch': Boolean(mismatch && mismatch.file_line === row.line),
      };
    },
    startEditPatch(patch) {
      this.editingPatchId = patch.id;
      this.patchDraft = patch.content || '';
      this.alignUndo = null;
      this.openPatches[patch.id] = true;
      this.$nextTick(() => {
        const ref = this.$refs.patchTextarea;
        const textarea = Array.isArray(ref) ? ref[0] : ref;
        if (textarea && textarea.focus) textarea.focus();
      });
    },
    cancelEditPatch() {
      this.editingPatchId = null;
      this.patchDraft = '';
      this.alignUndo = null;
    },
    async alignIndent(patch) {
      if (this.aligningPatchId) return;
      this.aligningPatchId = patch.id;
      try {
        const data = await api.post(
          `/api/sessions/${this.sessionId}/patches/${patch.id}/align-indent`,
          { align_added: this.alignAdded },
        );
        if (!data.aligned) {
          notify(data.reason || t('无法自动对齐缩进'), 'error');
          return;
        }
        const previous =
          this.editingPatchId === patch.id ? this.patchDraft : (patch.content || '');
        this.alignUndo = previous;
        this.editingPatchId = patch.id;
        this.patchDraft = data.content || '';
        this.openPatches[patch.id] = true;
        const summary = (data.changes || [])
          .map((change) =>
            t('hunk {hunk}: {sign}{count} {unit}', {
              hunk: change.hunk_index + 1,
              sign: change.mode === 'add' ? '+' : '-',
              count: change.count,
              unit: change.unit === 'tab' ? 'Tab' : t('空格'),
            }),
          )
          .join('；');
        notify(
          summary
            ? t('已对齐缩进（{summary}），请检查后保存', { summary })
            : t('已对齐缩进，请检查后保存'),
          'success',
        );
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.aligningPatchId = null;
      }
    },
    undoAlign() {
      if (this.alignUndo === null) return;
      this.patchDraft = this.alignUndo;
      this.alignUndo = null;
      notify(t('已撤销对齐，补丁文本已恢复'), 'info');
    },
    syncEditorScroll(event) {
      const ref = this.$refs.patchGutter;
      const gutter = Array.isArray(ref) ? ref[0] : ref;
      if (gutter) gutter.scrollTop = event.target.scrollTop;
    },
    insertPatchTab(event) {
      const textarea = event.target;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      this.patchDraft =
        this.patchDraft.slice(0, start) + '  ' + this.patchDraft.slice(end);
      this.$nextTick(() => {
        textarea.selectionStart = textarea.selectionEnd = start + 2;
      });
    },
    resetPatchDraft(patch) {
      this.patchDraft = patch.content || '';
      this.alignUndo = null;
    },
    async savePatch(patch) {
      try {
        await api.put(`/api/sessions/${this.sessionId}/patches/${patch.id}`, {
          content: this.patchDraft,
        });
        this.editingPatchId = null;
        this.patchDraft = '';
        this.alignUndo = null;
        notify(t('补丁已更新，正在重新检查'), 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    startEditCommit() {
      this.commitDraft = (this.parsed && this.parsed.commit_message) || '';
      this.editingCommit = true;
    },
    async saveCommit() {
      try {
        await api.put(`/api/sessions/${this.sessionId}/commit`, {
          commit_message: this.commitDraft,
        });
        this.editingCommit = false;
        notify(t('commit 文本已保存'), 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async runScript(script = null) {
      const source = (script || this.scriptText || this.scriptSource || '').trim();
      if (!source) {
        notify(t('没有可执行的 Python 脚本'), 'error');
        return null;
      }
      this.scriptRunning = true;
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/script/run`, {
          script: source,
        });
        this.scriptText = source;
        const report = data.report || {};
        const count = (data.patches || []).length;
        if (report.status === 'ok') {
          notify(t('Python 脚本执行完成，生成 {count} 个文件补丁', { count }), 'success');
        } else if (report.status === 'partial') {
          notify(
            t('脚本部分执行：{error}；已生成 {count} 个补丁', {
              error: report.error || t('有步骤失败'),
              count,
            }),
            'error',
          );
        } else {
          notify(
            t('脚本未执行：{reason}', {
              reason: report.reason || report.error || report.status,
            }),
            'error',
          );
        }
        await this.load();
        if (count) this.tab = 'review';
        else if (report.status !== 'ok') this.tab = 'script';
        return data;
      } catch (err) {
        notify(err.message, 'error');
        return null;
      } finally {
        this.scriptRunning = false;
      }
    },
    async copyScript() {
      if (!this.scriptText) return;
      await copyText(this.scriptText, t('Python 脚本'));
    },
    syncScriptGutter(event) {
      const gutter = this.$refs.scriptGutter;
      if (gutter && event && event.target) gutter.scrollTop = event.target.scrollTop;
    },
    jumpToScriptLine(line) {
      const total = this.scriptLineNumbers.length;
      const target = Math.max(1, Math.min(Number(line) || 1, total));
      const lines = this.scriptText.split('\n');
      let offset = 0;
      for (let index = 0; index < target - 1; index += 1) {
        offset += lines[index].length + 1;
      }
      const textarea = this.$refs.scriptEditor;
      if (!textarea) return;
      // preventScroll keeps the browser from scrolling the page to the top of
      // the textarea; we compute the real target line position ourselves.
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(offset, offset + (lines[target - 1] || '').length);
      if (this.scriptScrollFrame) cancelAnimationFrame(this.scriptScrollFrame);
      this.scriptScrollFrame = requestAnimationFrame(() => {
        this.scriptScrollFrame = null;
        this.scrollScriptToLine(target);
      });
    },
    scrollScriptToLine(target) {
      const textarea = this.$refs.scriptEditor;
      if (!textarea) return;
      const gutter = this.$refs.scriptGutter;
      const style = window.getComputedStyle(textarea);
      const lineHeight = parseFloat(style.lineHeight) || 20;
      const paddingTop = parseFloat(style.paddingTop) || 0;
      const lineTop = paddingTop + (target - 1) * lineHeight;

      // 1) Center the target line inside the textarea (if it scrolls).
      const taMax = Math.max(0, textarea.scrollHeight - textarea.clientHeight);
      const taTarget = Math.max(
        0,
        Math.min(lineTop - (textarea.clientHeight - lineHeight) / 2, taMax),
      );
      textarea.scrollTop = taTarget;

      // 2) Keep the gutter rows aligned with the textarea rows.
      if (gutter) {
        const gutterMax = Math.max(0, gutter.scrollHeight - gutter.clientHeight);
        const gutterTarget = Math.max(
          0,
          Math.min(lineTop - (gutter.clientHeight - lineHeight) / 2, gutterMax),
        );
        gutter.scrollTop = gutterTarget;
      }

      // 3) Scroll the whole page so the target line is near the viewport center.
      const rect = textarea.getBoundingClientRect();
      const lineDocTop = rect.top + window.scrollY + lineTop - textarea.scrollTop;
      const desired = lineDocTop - window.innerHeight / 2 + lineHeight / 2;
      const maxPage = Math.max(
        0,
        document.documentElement.scrollHeight - window.innerHeight,
      );
      const pageTarget = Math.max(0, Math.min(desired, maxPage));
      if (Math.abs(pageTarget - window.scrollY) > 2) {
        window.scrollTo({ top: pageTarget, behavior: 'smooth' });
      }
    },
    async submitAnswer() {
      if (!this.answerDraft.trim()) {
        notify(t('请先粘贴 AI 回答'), 'error');
        return;
      }
      this.busy = true;
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/answer`, {
          answer: this.answerDraft,
        });
        const count = (data.parsed && data.parsed.patches.length) || 0;
        const script = (data.parsed && data.parsed.script) || '';
        this.answerDraft = '';
        notify(t('解析完成，提取到 {count} 个文件补丁', { count }), count ? 'success' : 'info');
        this.tab = 'review';
        await this.load();
        if (this.pythonMode && script) {
          notify(t('已提取 Python 脚本，正在内存工作区执行…'), 'info');
          await this.runScript(script);
        }
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.busy = false;
      }
    },
    async loadBundleText() {
      if (this.bundleText) return this.bundleText;
      this.bundleLoading = true;
      try {
        this.bundleText = await api.text(`/api/sessions/${this.sessionId}/bundle`);
        return this.bundleText;
      } catch (err) {
        notify(err.message, 'error');
        return '';
      } finally {
        this.bundleLoading = false;
      }
    },
    async copyBundleText() {
      const text = await this.loadBundleText();
      if (text) await copyText(text, t('打包全文'));
    },
    async copyBundlePath() {
      if (!this.bundlePath) {
        notify(t('归档会话没有可直接复制的未压缩文件路径，请先重新载入'), 'error');
        return;
      }
      await copyText(this.bundlePath, t('打包文件路径'));
    },
    async copyCommit() {
      const text = (this.parsed && this.parsed.commit_message) || '';
      if (text) await copyText(text, t('commit 建议'));
    },
    async copyPrompt() {
      if (!this.requirement) {
        notify(t('该会话没有记录用户 Prompt'), 'error');
        return;
      }
      await copyText(this.requirement, t('用户 Prompt'));
    },
    async copyRepair(patch) {
      const status = this.statusFor(patch);
      if (!status || !status.repair) {
        notify(t('当前补丁没有 AI 修正请求'), 'error');
        return;
      }
      await copyText(status.repair, t('AI 修正请求'));
    },
    async loadDisk() {
      this.diskLoading = true;
      try {
        this.disk = await api.get(`/api/sessions/${this.sessionId}/disk-diff`);
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.diskLoading = false;
      }
    },
    async archiveSession() {
      const yes = await confirmDialog({
        title: t('归档会话'),
        message: t('归档后会话目录会变成 zip 压缩包，列表仍可见。若仍有未撤回的应用，撤回时会先解压。'),
        confirmText: t('归档'),
      });
      if (!yes) return;
      try {
        await api.post(`/api/sessions/${this.sessionId}/archive`);
        notify(t('会话已归档'), 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'archive_active_apply') {
          const force = await confirmDialog({
            title: t('仍有未撤回的补丁应用'),
            message: t('归档后如需撤回，PatchBridge 会先自动解压。确认归档吗？'),
            confirmText: t('仍然归档'),
            danger: true,
          });
          if (!force) return;
          try {
            await api.post(`/api/sessions/${this.sessionId}/archive`, {
              confirm_active_apply: true,
            });
            notify(t('会话已归档'), 'success');
            await this.load();
          } catch (secondError) {
            notify(secondError.message, 'error');
          }
        } else {
          notify(err.message, 'error');
        }
      }
    },
    async deleteSession() {
      const yes = await confirmDialog({
        title: t('删除会话'),
        message: t('删除会话不会还原磁盘文件。确定删除这条历史记录吗？'),
        confirmText: t('删除'),
        danger: true,
      });
      if (!yes) return;
      try {
        await api.delete(`/api/sessions/${this.sessionId}`);
        notify(t('会话已删除'), 'success');
        location.hash = '#/history';
      } catch (err) {
        if (err.code === 'active_apply') {
          const force = await confirmDialog({
            title: t('仍有未撤回的补丁应用'),
            message: t('删除会话不会影响磁盘上的代码，也不会自动撤回补丁。确认删除历史记录吗？'),
            confirmText: t('仍然删除'),
            danger: true,
          });
          if (!force) return;
          try {
            await api.delete(`/api/sessions/${this.sessionId}?confirm_active=true`);
            notify(t('会话已删除'), 'success');
            location.hash = '#/history';
          } catch (secondError) {
            notify(secondError.message, 'error');
          }
        } else {
          notify(err.message, 'error');
        }
      }
    },
    async abandonSession() {
      const yes = await confirmDialog({
        title: t('标记为已放弃'),
        message: t('标记后会话状态变为“已放弃”，可用于自动归档。不会修改磁盘文件。'),
        confirmText: t('标记放弃'),
      });
      if (!yes) return;
      try {
        await api.post(`/api/sessions/${this.sessionId}/abandon`);
        notify(t('会话已标记为放弃'), 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async reloadSession() {
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/reload`);
        notify(t('已生成新会话，并重新校验 hash'), 'success');
        location.hash = `#/session/${data.session_id}`;
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    exportUrl(format) {
      return `/api/sessions/${this.sessionId}/export?format=${format}`;
    },
    back() {
      if (this.meta.project_id) {
        location.hash = `#/project/${encodeURIComponent(this.meta.project_id)}`;
      } else {
        location.hash = '#/history';
      }
    },
    eventJson(event) {
      try {
        return JSON.stringify(event.data || {}, null, 2);
      } catch (err) {
        return '';
      }
    },
  },
  template: `
    <div class="page">
      <div v-if="loading" class="empty">{{ $t('加载会话…') }}</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <template v-else>
        <div class="page-header session-header">
          <div>
            <button class="btn link" @click="back">{{ $t('← 返回') }}</button>
            <h1>{{ $t('会话审阅') }}</h1>
            <div class="meta-row">
              <span>{{ meta.project_name }}</span>
              <span class="mono">{{ sessionId }}</span>
              <span class="badge" :class="'status-' + status">{{ statusText(status) }}</span>
              <span v-if="archived" class="badge muted">{{ $t('已归档') }}</span>
              <span v-if="meta.reloaded_from" class="badge muted">{{ $t('重新载入') }}</span>
            </div>
          </div>
          <div class="button-row wrap">
            <button class="btn" @click="reloadSession">{{ $t('重新载入') }}</button>
            <button class="btn" @click="archiveSession">{{ $t('归档') }}</button>
            <a class="btn" :href="exportUrl('md')">{{ $t('导出文档') }}</a>
            <a class="btn" :href="exportUrl('patch')">{{ $t('导出 patch') }}</a>
            <button class="btn danger-text" @click="deleteSession">{{ $t('删除') }}</button>
          </div>
        </div>

        <div v-if="archived" class="alert info">
          {{ $t('该会话已归档。详情可直接读取；应用、撤回、重新载入等操作会自动解压。') }}
        </div>

        <div class="tabs">
          <button :class="['tab', tab === 'review' ? 'active' : '']" @click="tab = 'review'">{{ $t('补丁审阅') }}</button>
          <button :class="['tab', tab === 'bundle' ? 'active' : '']" @click="tab = 'bundle'">{{ $t('打包文本') }}</button>
          <button :class="['tab', tab === 'answer' ? 'active' : '']" @click="tab = 'answer'">{{ $t('AI 回答') }}</button>
          <button v-if="pythonMode" :class="['tab', tab === 'script' ? 'active' : '']" @click="tab = 'script'">{{ $t('Python 脚本') }}</button>
          <button :class="['tab', tab === 'events' ? 'active' : '']" @click="tab = 'events'">{{ $t('事件') }}</button>
          <button :class="['tab', tab === 'disk' ? 'active' : '']" @click="tab = 'disk'; !disk && loadDisk()">{{ $t('磁盘差异') }}</button>
        </div>

        <section v-if="tab === 'review'" class="review-layout">
          <div class="review-main">
            <div class="panel prompt-panel">
              <div class="panel-head">
                <h2>{{ $t('用户 Prompt') }}</h2>
                <button class="btn tiny" @click="copyPrompt">{{ $t('复制 Prompt') }}</button>
              </div>
              <pre class="prose prompt-text">{{ requirement || $t('（该会话没有记录用户 Prompt）') }}</pre>
            </div>

            <div v-if="!parsed" class="panel answer-panel">
              <h2>{{ $t('粘贴 AI 的完整回答') }}</h2>
              <p class="muted">
                {{ $t('把 Web AI 输出的所有内容原样粘贴到这里。PatchBridge 会自动寻找修改说明、commit 建议和 unified diff。') }}
              </p>
              <textarea
                v-model="answerDraft"
                class="answer-editor"
                :placeholder="$t('粘贴 AI 回答全文…')"
              ></textarea>
              <button class="btn primary" :disabled="busy" @click="submitAnswer">
                {{ busy ? $t('解析中…') : $t('解析回答并提取补丁') }}
              </button>
            </div>

            <template v-else>
              <div class="panel">
                <div class="panel-head">
                  <h2>{{ $t('修改说明') }}</h2>
                </div>
                <pre class="prose">{{ parsed.explanation || $t('（未提取到修改说明）') }}</pre>
              </div>

              <div class="panel">
                <div class="panel-head">
                  <h2>{{ $t('Commit 建议') }}</h2>
                  <div class="small-actions">
                    <button class="btn tiny" @click="copyCommit">{{ $t('复制') }}</button>
                    <button v-if="!patchLocked" class="btn tiny" @click="startEditCommit">{{ $t('编辑') }}</button>
                  </div>
                </div>
                <div v-if="!editingCommit" class="commit-box mono">{{ parsed.commit_message || $t('（未提取到 commit 建议）') }}</div>
                <div v-else>
                  <textarea v-model="commitDraft" class="commit-editor" rows="3"></textarea>
                  <div class="button-row">
                    <button class="btn primary" @click="saveCommit">{{ $t('保存') }}</button>
                    <button class="btn" @click="editingCommit = false">{{ $t('取消') }}</button>
                  </div>
                </div>
              </div>

              <div v-if="warnings.length" class="alert warning">
                <strong>{{ $t('解析警告') }}</strong>
                <div v-for="(warning, idx) in warnings" :key="idx">• {{ warning }}</div>
              </div>

              <div v-if="applyResult" class="alert success">
                {{ $t('已应用 {count} 个文件：{paths}', { count: applyResult.paths.length, paths: applyResult.paths.join('、') }) }}
              </div>

              <div class="patch-toolbar">
                <div>
                  <button class="btn tiny" @click="toggleAll">{{ $t('反选未应用') }}</button>
                  <span class="muted">{{ $t('已选 {selected} / {total}', { selected: selectedIds.length, total: patches.length }) }}</span>
                  <label class="muted small context-picker">
                    {{ $t('上下文') }}
                    <select v-model.number="diffContext">
                      <option :value="0">0</option>
                      <option :value="1">1</option>
                      <option :value="3">3</option>
                      <option :value="5">5</option>
                      <option :value="10">10</option>
                      <option :value="20">20</option>
                      <option :value="50">50</option>
                    </select>
                  </label>
                </div>
                <div class="button-row">
                  <button
                    v-if="duplicateGroups.length && !patchLocked"
                    class="btn accent"
                    :disabled="merging"
                    @click="mergeDuplicates"
                  >{{ merging ? $t('合并中…') : $t('合并同文件 diff（{count} 组）', { count: duplicateGroups.length }) }}</button>
                  <button class="btn" @click="dryAll">{{ $t('全部 dry-run') }}</button>
                  <button class="btn primary" :disabled="busy || !selectedIds.length" @click="applySelected">
                    {{ $t('应用选中补丁') }}
                  </button>
                  <button v-if="hasUnrevertedApply" class="btn danger" :disabled="reverting" @click="revert">
                    {{ reverting ? $t('撤回中…') : $t('撤回最近一次应用') }}
                  </button>
                </div>
              </div>

              <div v-if="patchLocked" class="alert info">
                {{ $t('本会话已经应用过补丁，补丁与 commit 文本已锁定。未应用的文件仍可应用；如需修改补丁，请使用“重新载入”生成新会话。') }}
              </div>

              <article v-for="patch in patches" :key="patch.id" class="patch-card">
                <div class="patch-head">
                  <input
                    type="checkbox"
                    v-model="selected[patch.id]"
                    :disabled="isApplied(patch)"
                  />
                  <div class="patch-title mono">{{ patch.path }}</div>
                  <span v-if="patch.new_file" class="badge new">{{ $t('新增') }}</span>
                  <span v-if="isApplied(patch)" class="badge ok">{{ $t('已应用') }}</span>
                  <span class="patch-stats">+{{ patch.added }} / -{{ patch.removed }}</span>
                  <button class="icon-btn" @click="openPatches[patch.id] = !openPatches[patch.id]">
                    {{ openPatches[patch.id] ? '−' : '+' }}
                  </button>
                </div>
                <div class="badge-row">
                  <template v-if="!isApplied(patch)">
                    <span class="badge" :class="'hash-' + hashState(patch)">{{ hashText(hashState(patch)) }}</span>
                    <span class="badge" :class="'apply-' + applyState(patch)">{{ applyText(applyState(patch)) }}</span>
                    <span v-if="statusFor(patch)" class="badge" :class="'scope-' + statusFor(patch).scope_status">
                      {{ scopeText(statusFor(patch).scope_status) }}
                    </span>
                    <span
                      v-if="statusFor(patch) && statusFor(patch).engine === 'mpatch' && statusFor(patch).apply_status === 'ok'"
                      class="badge ok"
                    >{{ $t('mpatch 模糊') }}</span>
                    <span
                      v-else-if="statusFor(patch) && statusFor(patch).engine === 'mpatch'"
                      class="badge warning"
                    >{{ $t('mpatch 未命中') }}</span>
                    <span
                      v-else-if="statusFor(patch) && statusFor(patch).engine === 'strict+align'"
                      class="badge ok"
                    >{{ $t('自动对齐') }}</span>
                    <span v-if="statusFor(patch) && statusFor(patch).repair" class="badge warning">{{ $t('待 AI 修正') }}</span>
                    <span class="badge muted">p{{ patch.p_level || 1 }}</span>
                  </template>
                  <template v-else>
                    <span class="badge ok">{{ $t('本批次已应用') }}</span>
                    <span class="badge muted">p{{ patch.p_level || 1 }}</span>
                  </template>
                </div>
                <div v-if="statusFor(patch) && statusFor(patch).warnings.length" class="warnings small">
                  <div v-for="(warning, idx) in statusFor(patch).warnings" :key="idx">• {{ warning }}</div>
                </div>

                <div
                  v-if="statusFor(patch) && statusFor(patch).apply_status !== 'ok' && statusFor(patch).reason"
                  class="conflict-summary"
                >
                  <div>{{ statusFor(patch).reason }}</div>
                  <div v-if="!patchLocked && !isApplied(patch)" class="small-actions">
                    <button
                      class="btn tiny primary"
                      :disabled="aligningPatchId === patch.id"
                      @click="alignIndent(patch)"
                    >{{ aligningPatchId === patch.id ? $t('对齐中…') : $t('一键对齐缩进') }}</button>
                    <button class="btn tiny" @click="startEditPatch(patch)">{{ $t('打开补丁编辑器') }}</button>
                  </div>
                </div>

                <div v-if="statusFor(patch) && statusFor(patch).repair" class="repair-panel">
                  <div>
                    <strong>{{ $t('严格匹配和 mpatch 都没能应用这个补丁。') }}</strong>
                    <span class="muted">{{ $t('已按 mpatch 的失败位置生成修正请求，复制给 Web AI 重新生成即可。') }}</span>
                  </div>
                  <div class="small-actions">
                    <button class="btn tiny primary" @click="copyRepair(patch)">{{ $t('复制 AI 修正请求') }}</button>
                    <button class="btn tiny" @click="startEditPatch(patch)">{{ $t('仍要手工编辑') }}</button>
                  </div>
                  <details>
                    <summary>{{ $t('查看修正请求内容') }}</summary>
                    <pre class="repair-text mono">{{ statusFor(patch).repair }}</pre>
                  </details>
                </div>

                <div v-if="editingPatchId === patch.id" class="patch-edit">
                  <div class="editor-toolbar">
                    <div>
                      <strong>{{ $t('补丁编辑器') }}</strong>
                      <span class="muted">{{ $t('保存后会重新解析并 dry-run') }}</span>
                    </div>
                    <div class="small-actions editor-tools">
                      <label class="inline-check">
                        <input type="checkbox" v-model="alignAdded" />
                        <span>{{ $t('同时平移新增行') }}</span>
                      </label>
                      <button
                        class="btn tiny primary"
                        :disabled="aligningPatchId === patch.id"
                        @click="alignIndent(patch)"
                      >{{ aligningPatchId === patch.id ? $t('对齐中…') : $t('一键对齐缩进') }}</button>
                      <button v-if="alignUndo !== null" class="btn tiny" @click="undoAlign">{{ $t('撤销对齐') }}</button>
                      <button class="btn tiny" @click="resetPatchDraft(patch)">{{ $t('恢复当前补丁') }}</button>
                    </div>
                  </div>
                  <div
                    class="patch-editor-layout"
                    :class="{ 'with-reference': Boolean(diagnosticsFor(patch)) }"
                  >
                    <div class="patch-editor-main">
                      <div class="patch-editor-grid">
                        <pre ref="patchGutter" class="editor-gutter">{{ editorGutterText }}</pre>
                        <textarea
                          ref="patchTextarea"
                          v-model="patchDraft"
                          class="code-editor patch-code-editor"
                          spellcheck="false"
                          @scroll="syncEditorScroll"
                          @keydown.tab.prevent="insertPatchTab"
                        ></textarea>
                      </div>
                      <div class="button-row">
                        <button class="btn primary" @click="savePatch(patch)">{{ $t('保存并重新检查') }}</button>
                        <button class="btn" @click="cancelEditPatch">{{ $t('取消') }}</button>
                      </div>
                    </div>

                    <aside v-if="diagnosticsFor(patch)" class="patch-editor-reference">
                      <div v-if="alignUndo !== null" class="alert success small">
                        {{ $t('已填入对齐后的补丁，但尚未保存。下面是保存前的冲突参考，便于核对。') }}
                      </div>
                      <div class="alert warning mismatch-hint">
                        <strong>{{ $t('冲突定位：') }}{{ diagnosticsFor(patch).hunk_header }}</strong>
                        <div>{{ diagnosticsFor(patch).hint }}</div>
                        <div v-if="mismatchFor(patch) && mismatchFor(patch).kind === 'indentation'" class="mono">
                          {{ $t('补丁缩进 {patch} 个空格 / 文件缩进 {file} 个空格', { patch: mismatchFor(patch).patch_indent, file: mismatchFor(patch).file_indent }) }}
                        </div>
                      </div>
                      <div class="mismatch-columns">
                        <div class="mismatch-column">
                          <h4>{{ $t('补丁上下文') }}</h4>
                          <div class="compare-list">
                            <div
                              v-for="(row, idx) in diagnosticsFor(patch).patch_rows"
                              :key="'p-' + idx"
                              :class="['compare-row', patchRowClass(patch, row, idx)]"
                            >
                              <span class="compare-ln">{{ row.old_line || '·' }}</span>
                              <span class="compare-tag">{{ row.tag === ' ' ? '·' : row.tag }}</span>
                              <span class="compare-text">{{ row.text || ' ' }}</span>
                            </div>
                          </div>
                        </div>
                        <div class="mismatch-column">
                          <h4>{{ $t('当前文件') }}</h4>
                          <div class="compare-list">
                            <div
                              v-for="row in diagnosticsFor(patch).file_rows"
                              :key="'f-' + row.line"
                              :class="['compare-row', fileRowClass(patch, row)]"
                            >
                              <span class="compare-ln">{{ row.line }}</span>
                              <span class="compare-tag"> </span>
                              <span class="compare-text">{{ row.text || ' ' }}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </aside>
                  </div>
                </div>
                <div
                  v-if="editingPatchId !== patch.id && openPatches[patch.id] && statusFor(patch) && statusFor(patch).final_patch"
                  class="alert info small"
                  style="margin: 0 15px 10px;"
                >
                  {{ $t('mpatch 已在临时副本中完成模糊应用，下面显示的是由副本 git diff 生成的最终补丁；应用时会再次用严格引擎校验。') }}
                </div>
                <div v-if="editingPatchId !== patch.id && openPatches[patch.id]" class="diff-area">
                  <side-diff
                    v-if="statusFor(patch) && statusFor(patch).diff_rows"
                    :rows="statusFor(patch).diff_rows.rows"
                    :context="diffContext"
                  />
                  <diff-view v-else :content="displayPatch(patch)" />
                  <details class="raw-patch">
                    <summary>{{ $t('查看原始补丁') }}</summary>
                    <diff-view :content="displayPatch(patch)" />
                  </details>
                </div>

                <div class="patch-actions">
                  <button class="btn tiny" @click="dryOne(patch)">{{ $t('单文件 dry-run') }}</button>
                  <button
                    v-if="!patchLocked && !isApplied(patch)"
                    class="btn tiny"
                    @click="startEditPatch(patch)"
                  >{{ $t('编辑补丁') }}</button>
                </div>
              </article>
            </template>
          </div>

          <aside class="review-side">
            <div class="panel side-panel">
              <h3>{{ $t('会话信息') }}</h3>
              <dl class="meta-list">
                <dt>{{ $t('工程') }}</dt><dd>{{ meta.project_name }}</dd>
                <dt>{{ $t('根目录') }}</dt><dd class="mono break">{{ meta.root }}</dd>
                <dt>{{ $t('创建') }}</dt><dd>{{ shortDate(meta.created_at) }}</dd>
                <dt>{{ $t('文件数') }}</dt><dd>{{ meta.file_count }}</dd>
                <dt>{{ $t('大小') }}</dt><dd>{{ formatBytes(meta.total_bytes) }}</dd>
              </dl>
            </div>
            <div class="panel side-panel">
              <h3>{{ $t('交给 AI 的文本') }}</h3>
              <p class="muted small">{{ $t('可以复制全文，或复制文件完整路径。') }}</p>
              <div class="path-box mono break">{{ bundlePath || $t('（已归档）') }}</div>
              <div class="button-row wrap">
                <button class="btn tiny" @click="copyBundlePath">{{ $t('复制文件路径') }}</button>
                <button class="btn tiny" @click="copyBundleText">{{ $t('复制全文') }}</button>
              </div>
            </div>
            <div class="panel side-panel">
              <h3>{{ $t('快捷操作') }}</h3>
              <div class="button-row wrap">
                <button class="btn tiny" @click="tab = 'answer'">{{ $t('替换 AI 回答') }}</button>
                <button class="btn tiny" @click="tab = 'events'">{{ $t('查看事件') }}</button>
                <button class="btn tiny" @click="tab = 'disk'">{{ $t('比较磁盘') }}</button>
                <button
                  v-if="!details.has_any_apply && status !== 'abandoned'"
                  class="btn tiny"
                  @click="abandonSession"
                >{{ $t('标记为已放弃') }}</button>
              </div>
            </div>
          </aside>
        </section>

        <section v-if="tab === 'bundle'" class="panel">
          <div class="panel-head">
            <h2>{{ $t('打包文本') }}</h2>
            <div class="button-row">
              <button class="btn" @click="copyBundlePath">{{ $t('复制文件路径') }}</button>
              <button class="btn primary" @click="copyBundleText">{{ $t('复制全文') }}</button>
              <a class="btn" :href="'/api/sessions/' + sessionId + '/bundle'">{{ $t('下载') }}</a>
            </div>
          </div>
          <div class="path-copy-row">
            <code class="mono path-box break">{{ bundlePath || $t('（已归档，压缩包：{path}）', { path: archivePath }) }}</code>
          </div>
          <div v-if="bundleLoading" class="muted">{{ $t('读取中…') }}</div>
          <pre v-else-if="bundleText" class="bundle-full">{{ bundleText }}</pre>
          <div v-else class="empty">
            <button class="btn primary" @click="loadBundleText">{{ $t('加载 / 复制完整文本') }}</button>
          </div>
        </section>

        <section v-if="tab === 'answer'" class="panel">
          <div class="panel-head">
            <h2>{{ $t('AI 回答原文') }}</h2>
          </div>
          <div v-if="!patchLocked" class="answer-replace">
            <p class="muted">{{ $t('重新粘贴一份完整回答会覆盖当前解析结果。已应用的会话不能重新解析。') }}</p>
            <textarea v-model="answerDraft" class="answer-editor" :placeholder="$t('粘贴新的 AI 回答全文…')"></textarea>
            <button class="btn primary" :disabled="busy" @click="submitAnswer">{{ $t('重新解析') }}</button>
          </div>
          <pre class="prose answer-raw">{{ answerText || $t('（还没有保存 AI 回答）') }}</pre>
        </section>

        <section v-if="tab === 'script' && pythonMode" class="panel script-panel">
          <div class="panel-head">
            <h2>{{ $t('Python 补丁脚本') }}</h2>
            <div class="small-actions">
              <button class="btn tiny" @click="copyScript">{{ $t('复制脚本') }}</button>
              <button class="btn primary tiny" :disabled="scriptRunning || patchLocked" @click="runScript()">
                {{ scriptRunning ? $t('执行中…') : $t('执行脚本') }}
              </button>
            </div>
          </div>
          <p class="muted">
            {{ $t('脚本只会修改内存中的工作区；执行成功或部分成功后才会生成补丁。真实文件在“应用选中补丁”之前不会改变。') }}
          </p>
          <div class="script-editor-wrap">
            <div ref="scriptGutter" class="script-gutter" aria-hidden="true">
              <div v-for="line in scriptLineNumbers" :key="line" :id="'script-line-' + line">{{ line }}</div>
            </div>
            <textarea
              ref="scriptEditor"
              v-model="scriptText"
              class="code-editor script-editor"
              spellcheck="false"
              wrap="off"
              :placeholder="$t('AI 输出的 Python 补丁脚本…')"
              @scroll="syncScriptGutter"
            ></textarea>
          </div>
          <div v-if="patchLocked" class="alert info">{{ $t('会话已应用补丁，脚本已锁定；如需再改请“重新载入”。') }}</div>

          <div v-if="scriptReport" class="script-report">
            <div class="script-report-head">
              <span class="badge" :class="scriptReport.status === 'ok' ? 'ok' : (scriptReport.status === 'partial' ? 'warning' : 'error')">
                {{ scriptReport.status }}
              </span>
              <span class="muted">{{ scriptReport.reason || scriptReport.error || '' }}</span>
              <button
                v-if="scriptReport.error_line"
                class="line-link"
                type="button"
                @click="jumpToScriptLine(scriptReport.error_line)"
              >{{ $t('第 {line} 行', { line: scriptReport.error_line }) }}</button>
              <span class="muted mono">{{ scriptReport.elapsed_ms }} ms</span>
            </div>
            <div v-if="scriptReport.warnings && scriptReport.warnings.length" class="alert warning small">
              <div v-for="(warning, idx) in scriptReport.warnings" :key="idx">· {{ warning }}</div>
            </div>
            <details v-if="scriptReport.stdout" class="script-details" open>
              <summary>stdout</summary>
              <pre class="script-stdout">{{ scriptReport.stdout }}</pre>
            </details>
            <details v-if="scriptReport.steps && scriptReport.steps.length" class="script-details" open>
              <summary>{{ $t('执行步骤（{count}）', { count: scriptReport.steps.length }) }}</summary>
              <div v-for="step in scriptReport.steps" :key="step.index" class="script-step">
                <span class="badge" :class="step.status === 'ok' ? 'ok' : 'warning'">{{ step.status }}</span>
                <span class="mono">#{{ step.index }} {{ step.api }}</span>
                <code>{{ step.path }}</code>
                <span class="muted">{{ step.message }}</span>
                <button v-if="step.line" class="line-link" type="button" @click="jumpToScriptLine(step.line)">
                  {{ $t('第 {line} 行', { line: step.line }) }}
                </button>
              </div>
            </details>
          </div>
        </section>

        <section v-if="tab === 'events'" class="panel">
          <div class="panel-head"><h2>{{ $t('操作事件') }}</h2></div>
          <div v-if="!events.length" class="muted">{{ $t('暂无事件') }}</div>
          <div v-for="event in events" :key="event.id || event.seq" class="event-row">
            <div class="event-head">
              <span class="badge">{{ event.type }}</span>
              <span class="muted mono">{{ shortDate(event.at) }}</span>
              <span class="muted mono">#{{ event.seq }}</span>
            </div>
            <pre class="event-json">{{ eventJson(event) }}</pre>
          </div>
        </section>

        <section v-if="tab === 'disk'" class="panel">
          <div class="panel-head">
            <h2>{{ $t('“应用后”与当前磁盘的差异') }}</h2>
            <button class="btn" :disabled="diskLoading" @click="loadDisk">
              {{ diskLoading ? $t('比较中…') : $t('重新比较') }}
            </button>
          </div>
          <div v-if="!disk" class="muted">{{ $t('点击“重新比较”生成差异。') }}</div>
          <div v-else-if="!disk.available" class="alert info">{{ disk.message }}</div>
          <div v-else>
            <div class="alert" :class="disk.files.length ? 'warning' : 'success'">{{ disk.message }}</div>
            <div v-for="file in disk.files" :key="file.path" class="disk-file">
              <h3 class="mono">{{ file.path }} <span class="badge">{{ file.status }}</span></h3>
              <pre class="prose">{{ file.diff || $t('（无法生成文本 diff）') }}</pre>
            </div>
          </div>
        </section>

        <div v-if="confirmApply" class="modal-backdrop" @click.self="confirmApply = null">
          <div class="modal">
            <div class="modal-head">
              <h2>{{ $t('确认 hash 变化') }}</h2>
              <button class="icon-btn" @click="confirmApply = null">×</button>
            </div>
            <p class="warning-text">
              {{ $t('以下文件在打包后被外部修改。应用补丁会以当前磁盘内容为基准；请确认你了解这一点。') }}
            </p>
            <label v-for="path in confirmApply.paths" :key="path" class="check-row">
              <input type="checkbox" v-model="hashConfirmChecked[path]" />
              <span class="mono">{{ path }}</span>
            </label>
            <div class="modal-actions">
              <button class="btn" @click="confirmApply = null">{{ $t('取消') }}</button>
              <button class="btn danger" :disabled="busy" @click="confirmHashApply">{{ $t('确认并应用') }}</button>
            </div>
          </div>
        </div>
      </template>
    </div>
  `,
};

const HistoryPage = {
  name: 'HistoryPage',
  data() {
    return {
      sessions: [],
      projects: [],
      loading: true,
      index: null,
      filters: {
        project_id: '',
        status: '',
        q: '',
        date_from: '',
        date_to: '',
        archived: '',
      },
    };
  },
  mounted() {
    this.load();
    api.get('/api/projects').then((data) => {
      this.projects = data.projects || [];
    }).catch(() => {});
  },
  methods: {
    formatBytes,
    shortDate,
    statusText,
    async load() {
      this.loading = true;
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(this.filters)) {
        if (value !== '') params.set(key, value);
      }
      try {
        const data = await api.get(`/api/sessions?${params.toString()}`);
        this.sessions = data.sessions || [];
        this.index = data.index || null;
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.loading = false;
      }
    },
    async rebuild() {
      try {
        await api.post('/api/index/rebuild');
        notify(t('索引已重建'), 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    open(session) {
      location.hash = `#/session/${session.id}`;
    },
  },
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>{{ $t('会话历史') }}</h1>
          <p class="muted">{{ $t('所有会话均以纯文本保存，可按工程、状态、日期筛选。') }}</p>
        </div>
        <button v-if="index && index.status && index.status.stale" class="btn accent" @click="rebuild">
          {{ $t('索引不一致，重建') }}
        </button>
      </div>

      <div v-if="index && index.rebuilt" class="alert info">{{ $t('检测到会话目录与索引不一致，已自动重建索引。') }}</div>

      <div class="filter-bar">
        <select v-model="filters.project_id" @change="load">
          <option value="">{{ $t('全部工程') }}</option>
          <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
        <select v-model="filters.status" @change="load">
          <option value="">{{ $t('全部状态') }}</option>
          <option value="packed">{{ $t('待 AI 回答') }}</option>
          <option value="parsed">{{ $t('已解析') }}</option>
          <option value="applied">{{ $t('已应用') }}</option>
          <option value="reverted">{{ $t('已撤回') }}</option>
          <option value="abandoned">{{ $t('已放弃') }}</option>
        </select>
        <select v-model="filters.archived" @change="load">
          <option value="">{{ $t('全部存储') }}</option>
          <option value="false">{{ $t('未归档') }}</option>
          <option value="true">{{ $t('已归档') }}</option>
        </select>
        <input v-model="filters.q" :placeholder="$t('搜索标题 / 工程 / ID')" @keyup.enter="load" />
        <input v-model="filters.date_from" type="date" @change="load" />
        <input v-model="filters.date_to" type="date" @change="load" />
        <button class="btn" @click="load">{{ $t('刷新') }}</button>
      </div>

      <div v-if="loading" class="empty">{{ $t('加载中…') }}</div>
      <div v-else-if="!sessions.length" class="empty">{{ $t('没有符合条件的会话。') }}</div>
      <div v-else class="session-list">
        <article v-for="session in sessions" :key="session.id" class="session-row" @click="open(session)">
          <div class="session-main">
            <div class="session-title-line">
              <span class="session-prompt">{{ session.title }}</span>
              <span class="badge" :class="'status-' + session.status">{{ statusText(session.status) }}</span>
              <span v-if="session.archived" class="badge muted">zip</span>
            </div>
            <div class="meta-row">
              <span>{{ session.project_name }}</span>
              <span class="mono">{{ session.id }}</span>
              <span>{{ shortDate(session.created_at) }}</span>
            </div>
          </div>
          <div class="session-stats">
            <span>{{ $t('{count} 文件', { count: session.file_count }) }}</span>
            <span>{{ formatBytes(session.bundle_bytes) }}</span>
            <span>{{ $t('{count} 补丁', { count: session.patches }) }}</span>
            <span v-if="session.warnings" class="badge warning">{{ $t('{count} 警告', { count: session.warnings }) }}</span>
          </div>
        </article>
      </div>

      <details v-if="index" class="index-details">
        <summary>{{ $t('索引状态') }}</summary>
        <pre>{{ JSON.stringify(index.status, null, 2) }}</pre>
      </details>
    </div>
  `,
};

const SettingsPage = {
  name: 'SettingsPage',
  data() {
    return {
      settings: null,
      meta: null,
      loading: true,
      saving: false,
      largeMb: 1,
      error: '',
    };
  },
  computed: {
    // 路径里有反斜杠，放进模板表达式会被当成转义符，所以在 JS 里算好再用。
    mpatchPlaceholder() {
      return t('留空自动查找 mpatch 或 C:\\portable_apps\\bin\\mpatch.exe');
    },
  },
  mounted() {
    this.load();
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const data = await api.get('/api/settings');
        this.settings = data.settings;
        this.meta = {
          prompt_path_resolved: data.prompt_path_resolved,
          prompt_exists: data.prompt_exists,
          python_prompt_path_resolved: data.python_prompt_path_resolved,
          python_prompt_exists: data.python_prompt_exists,
          mpatch: data.mpatch || {},
        };
        this.largeMb = Math.max(0.1, (Number(this.settings.large_file_bytes) || 1048576) / 1024 / 1024);
      } catch (err) {
        this.error = err.message;
      } finally {
        this.loading = false;
      }
    },
    async save() {
      this.saving = true;
      try {
        const payload = {
          ...this.settings,
          large_file_bytes: Math.round(Number(this.largeMb) * 1024 * 1024),
        };
        const data = await api.put('/api/settings', payload);
        this.settings = data.settings;
        notify(t('设置已保存'), 'success');
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.saving = false;
      }
    },
    async reloadMeta() {
      try {
        const data = await api.get('/api/settings');
        this.meta = {
          prompt_path_resolved: data.prompt_path_resolved,
          prompt_exists: data.prompt_exists,
          python_prompt_path_resolved: data.python_prompt_path_resolved,
          python_prompt_exists: data.python_prompt_exists,
          mpatch: data.mpatch || {},
        };
      } catch (err) {
        notify(err.message, 'error');
      }
    },
  },
  template: `
    <div class="page narrow">
      <div class="page-header">
        <div><h1>{{ $t('设置') }}</h1><p class="muted">{{ $t('这些设置对全部工程生效。') }}</p></div>
      </div>
      <div v-if="loading" class="empty">{{ $t('加载中…') }}</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <div v-else class="panel settings-panel">
        <label class="field-label">{{ $t('大文件阈值（MB）') }}</label>
        <input v-model.number="largeMb" type="number" min="0.1" step="0.1" />
        <p class="hint">{{ $t('超过该大小的文件默认不进入文件树，也不会被选中。') }}</p>

        <label class="field-label">{{ $t('自动归档') }}</label>
        <label class="check-row">
          <input type="checkbox" v-model="settings.auto_archive_enabled" />
          <span>{{ $t('启用自动归档（默认关闭）') }}</span>
        </label>
        <label class="field-label">{{ $t('自动归档天数') }}</label>
        <input v-model.number="settings.auto_archive_days" type="number" min="1" />
        <p class="hint">
          {{ $t('只归档没有未撤回 apply、且状态为已撤回或已放弃、超过指定天数的会话。') }}
        </p>

        <label class="field-label">{{ $t('提示词模板路径') }}</label>
        <input v-model="settings.prompt_template_path" :placeholder="$t('留空使用内置模板')" />
        <div class="path-copy-row" v-if="meta">
          <code class="mono path-box break">{{ meta.prompt_path_resolved }}</code>
          <span class="badge" :class="meta.prompt_exists ? 'ok' : 'bad'">
            {{ meta.prompt_exists ? $t('存在') : $t('不存在') }}
          </span>
          <button class="btn tiny" @click="reloadMeta">{{ $t('检查') }}</button>
        </div>
        <p class="hint">
          {{ $t('模板支持') }} <code v-pre>{{PROJECT_NAME}}</code>、<code v-pre>{{FILE_COUNT}}</code>、
          <code v-pre>{{TOTAL_BYTES}}</code> {{ $t('等占位符。') }}
        </p>

        <label class="field-label">{{ $t('Python 模式提示词模板路径') }}</label>
        <input v-model="settings.python_prompt_template_path" :placeholder="$t('留空使用内置 Python SDK 模板')" />
        <div class="path-copy-row" v-if="meta">
          <code class="mono path-box break">{{ meta.python_prompt_path_resolved }}</code>
          <span class="badge" :class="meta.python_prompt_exists ? 'ok' : 'bad'">
            {{ meta.python_prompt_exists ? $t('存在') : $t('不存在') }}
          </span>
          <button class="btn tiny" @click="reloadMeta">{{ $t('检查') }}</button>
        </div>
        <label class="field-label">{{ $t('Python 脚本超时（秒）') }}</label>
        <input v-model.number="settings.script_timeout_seconds" type="number" min="1" max="300" />
        <label class="field-label">{{ $t('脚本 stdout 最大字符数') }}</label>
        <input v-model.number="settings.script_max_output_chars" type="number" min="1000" />
        <label class="field-label">{{ $t('diff 默认上下文行数（0–50）') }}</label>
        <input v-model.number="settings.diff_context_lines" type="number" min="0" max="50" />
        <p class="hint">{{ $t('Python 脚本在独立线程中执行，只修改内存工作区；超时会丢弃结果，不会写真实文件。') }}</p>

        <label class="field-label">{{ $t('mpatch 可执行文件') }}</label>
        <input v-model="settings.mpatch_path" :placeholder="mpatchPlaceholder" />
        <div v-if="meta && meta.mpatch" class="path-copy-row">
          <code class="mono path-box break">{{ meta.mpatch.path || $t('未找到') }}</code>
          <span class="badge" :class="meta.mpatch.available ? 'ok' : 'bad'">
            {{ meta.mpatch.available ? (meta.mpatch.version || $t('可用')) : $t('不可用') }}
          </span>
          <button class="btn tiny" @click="reloadMeta">{{ $t('重新检测') }}</button>
        </div>
        <p class="hint">
          {{ $t('严格引擎失败后，会自动在临时副本中调用 mpatch；真实工程目录不会交给 mpatch 写入。') }}
        </p>

        <label class="field-label">{{ $t('mpatch 模糊相似度阈值（0–1）') }}</label>
        <input v-model.number="settings.mpatch_fuzz_factor" type="number" min="0" max="1" step="0.05" />
        <p class="hint">{{ $t('默认 0.7。越低越容易匹配，但误配风险也越高。') }}</p>

        <label class="field-label">{{ $t('mpatch 超时（秒）') }}</label>
        <input v-model.number="settings.mpatch_timeout_seconds" type="number" min="5" />
        <label class="field-label">{{ $t('AI 修正请求：整文件附加上限（字节）') }}</label>
        <input v-model.number="settings.mpatch_repair_full_file_bytes" type="number" min="1024" />
        <p class="hint">{{ $t('文件不超过该值时附完整内容，否则只附失败位置附近的上下文。') }}</p>
        <label class="field-label">{{ $t('AI 修正请求：上下文行数') }}</label>
        <input v-model.number="settings.mpatch_repair_context_lines" type="number" min="5" />

        <label class="field-label">{{ $t('备份保留天数') }}</label>
        <input v-model.number="settings.backup_retention_days" type="number" min="1" />
        <p class="hint">{{ $t('清理备份时不会删除仍有未撤回 apply 的备份。') }}</p>

        <label class="field-label">{{ $t('最大扫描文件数') }}</label>
        <input v-model.number="settings.max_files" type="number" min="1" />
        <label class="field-label">{{ $t('单次打包大小上限（字节）') }}</label>
        <input v-model.number="settings.max_bundle_bytes" type="number" min="1024" />

        <div class="button-row">
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? $t('保存中…') : $t('保存设置') }}</button>
        </div>
      </div>
    </div>
  `,
};

const App = {
  components: { ProjectsPage, ProjectPage, SessionPage, HistoryPage, SettingsPage },
  data() {
    return {
      route: { name: 'projects', id: '' },
      ui,
      answerText: '',
      sidebar: {
        projects: [],
        sessions: [],
        loading: true,
      },
      projectsExpanded: true,
      historyExpanded: true,
      autoPollTimer: null,
      locale: getLocale(),
      appVersion: '',
    };
  },
  computed: {
    sessionId() {
      return this.route.id;
    },
    recentProjects() {
      const projects = [...this.sidebar.projects];
      const lastSeen = new Map();
      for (const session of this.sidebar.sessions) {
        const projectId = session.project_id;
        if (!projectId) continue;
        const stamp = session.updated_at || session.created_at || '';
        const prev = lastSeen.get(projectId) || '';
        if (stamp > prev) lastSeen.set(projectId, stamp);
      }
      projects.sort((a, b) => {
        const ta = lastSeen.get(a.id) || '';
        const tb = lastSeen.get(b.id) || '';
        if (ta !== tb) return tb.localeCompare(ta);
        return a.name.localeCompare(b.name);
      });
      return projects.slice(0, 8);
    },
    recentSessions() {
      return this.sidebar.sessions.slice(0, 8);
    },
  },
  mounted() {
    window.addEventListener('hashchange', this.updateRoute);
    try {
      const projects = localStorage.getItem('patchbridge.sidebar.projectsExpanded');
      if (projects !== null) this.projectsExpanded = projects === '1';
      const history = localStorage.getItem('patchbridge.sidebar.historyExpanded');
      if (history !== null) this.historyExpanded = history === '1';
    } catch (err) {
      /* localStorage 不可用时使用默认展开状态 */
    }
    this.updateRoute(true);
    this.loadAppVersion();
    this.pollAutoState();
    this.autoPollTimer = setInterval(() => this.pollAutoState(), 1500);
  },
  beforeUnmount() {
    if (this.autoPollTimer) {
      clearInterval(this.autoPollTimer);
      this.autoPollTimer = null;
    }
  },
  methods: {
    async loadAppVersion() {
      try {
        const meta = await api.get('/api/meta');
        if (meta && meta.version) this.appVersion = `v${meta.version}`;
      } catch (err) {
        /* 版本号只是展示，取不到就不显示 */
      }
    },
    async pollAutoState() {
      try {
        const data = await api.get('/api/auto-deepseek/status');
        const wasRunning = Boolean(ui.auto.running);
        ui.auto.running = Boolean(data.running);
        ui.auto.sessionId = data.session_id || null;
        ui.auto.message = data.message || '';
        if (
          wasRunning &&
          !ui.auto.running &&
          data.success !== null &&
          data.success !== undefined
        ) {
          notify(
            data.success
              ? t('DeepSeek 自动输入完成，请人工确认后手动提交')
              : t('自动输入失败：{error}', { error: data.message || '' }),
            data.success ? 'success' : 'error',
          );
        }
      } catch (err) {
        /* 自动化状态查询失败时静默忽略 */
      }
    },
    updateRoute(initial = false) {
      const hash = location.hash.replace(/^#/, '') || '/projects';
      const parts = hash.split('/').filter(Boolean);
      const name = parts[0] || 'projects';
      this.route = {
        name,
        id: parts[1] ? decodeURIComponent(parts[1]) : '',
      };
      this.answerText = '';
      if (initial) {
        if (name === 'project') this.projectsExpanded = true;
        if (name === 'session') this.historyExpanded = true;
      }
      this.loadSidebar();
    },
    async loadSidebar() {
      try {
        const [projectsData, sessionsData] = await Promise.all([
          api.get('/api/projects'),
          api.get('/api/sessions'),
        ]);
        this.sidebar.projects = projectsData.projects || [];
        this.sidebar.sessions = sessionsData.sessions || [];
      } catch (err) {
        /* 侧边栏加载失败不应阻断主流程 */
      } finally {
        this.sidebar.loading = false;
      }
    },
    toggleProjects() {
      this.projectsExpanded = !this.projectsExpanded;
      try {
        localStorage.setItem(
          'patchbridge.sidebar.projectsExpanded',
          this.projectsExpanded ? '1' : '0',
        );
      } catch (err) {
        /* ignore */
      }
    },
    toggleHistory() {
      this.historyExpanded = !this.historyExpanded;
      try {
        localStorage.setItem(
          'patchbridge.sidebar.historyExpanded',
          this.historyExpanded ? '1' : '0',
        );
      } catch (err) {
        /* ignore */
      }
    },
    isProjectActive(id) {
      return this.route.name === 'project' && this.route.id === id;
    },
    isSessionActive(id) {
      return this.route.name === 'session' && this.route.id === id;
    },
    isProjectsSectionActive() {
      return this.route.name === 'projects' || this.route.name === 'project';
    },
    isHistorySectionActive() {
      return this.route.name === 'history' || this.route.name === 'session';
    },
    go(path) {
      location.hash = path;
    },
    resolveConfirm(value) {
      closeConfirm(value);
    },
    switchLocale(locale) {
      if (locale === this.locale) return;
      this.locale = locale;
      // 整页 reload：让后端按新的 Accept-Language 重新出诊断文本和提示词，
      // reload() 会保留 location.hash，当前页面不会丢。
      reloadWithLocale(locale);
    },
  },
  template: `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand" @click="go('#/projects')">
          <span class="brand-mark">PB</span>
          <div>
            <strong>PatchBridge</strong>
            <small>{{ $t('Web AI → 安全补丁') }}</small>
          </div>
        </div>
        <nav>
          <div class="nav-mobile">
            <a :data-short="$t('工程')" href="#/projects" :title="$t('打开工程列表页面')" :class="['nav-item', isProjectsSectionActive() ? 'active' : '']">{{ $t('工程') }}</a>
            <a :data-short="$t('历史')" href="#/history" :title="$t('打开历史会话页面')" :class="['nav-item', isHistorySectionActive() ? 'active' : '']">{{ $t('历史会话') }}</a>
          </div>
          <div :class="['nav-group', isProjectsSectionActive() ? 'active' : '']">
            <div class="nav-group-header">
              <button
                class="caret"
                type="button"
                :aria-expanded="projectsExpanded ? 'true' : 'false'"
                :aria-label="$t('工程')"
                @click="toggleProjects"
              >{{ projectsExpanded ? '▾' : '▸' }}</button>
              <span class="nav-group-title" @click="toggleProjects">{{ $t('工程') }}</span>
              <a class="open-link" href="#/projects" :title="$t('打开工程列表页面')">↗</a>
            </div>
            <div v-if="projectsExpanded" class="nav-group-children">
              <div v-if="sidebar.loading" class="nav-group-empty">{{ $t('加载中…') }}</div>
              <div v-else-if="!recentProjects.length" class="nav-group-empty">{{ $t('暂无工程') }}</div>
              <a
                v-for="project in recentProjects"
                :key="project.id"
                :href="'#/project/' + encodeURIComponent(project.id)"
                :class="['nav-subitem', isProjectActive(project.id) ? 'active' : '']"
                :title="project.name"
              >{{ project.name }}</a>
            </div>
          </div>
          <div :class="['nav-group', isHistorySectionActive() ? 'active' : '']">
            <div class="nav-group-header">
              <button
                class="caret"
                type="button"
                :aria-expanded="historyExpanded ? 'true' : 'false'"
                :aria-label="$t('历史会话')"
                @click="toggleHistory"
              >{{ historyExpanded ? '▾' : '▸' }}</button>
              <span class="nav-group-title" @click="toggleHistory">{{ $t('历史会话') }}</span>
              <a class="open-link" href="#/history" :title="$t('打开历史会话页面')">↗</a>
            </div>
            <div v-if="historyExpanded" class="nav-group-children">
              <div v-if="sidebar.loading" class="nav-group-empty">{{ $t('加载中…') }}</div>
              <div v-else-if="!recentSessions.length" class="nav-group-empty">{{ $t('暂无会话') }}</div>
              <a
                v-for="session in recentSessions"
                :key="session.id"
                :href="'#/session/' + encodeURIComponent(session.id)"
                :class="['nav-subitem', isSessionActive(session.id) ? 'active' : '']"
                :title="session.title"
              >{{ session.title }}</a>
            </div>
          </div>
          <a :data-short="$t('设置')" href="#/settings" :title="$t('设置')" :class="['nav-item', route.name === 'settings' ? 'active' : '']">{{ $t('设置') }}</a>
        </nav>
        <div class="sidebar-foot">
          <div class="lang-switch" role="group" :aria-label="$t('界面语言')">
            <button
              type="button"
              class="lang-btn"
              :class="{ active: locale === 'zh' }"
              :aria-pressed="locale === 'zh' ? 'true' : 'false'"
              :lang="'zh-CN'"
              :title="$t('切换到中文界面')"
              @click="switchLocale('zh')"
            >中文</button>
            <button
              type="button"
              class="lang-btn"
              :class="{ active: locale === 'en' }"
              :aria-pressed="locale === 'en' ? 'true' : 'false'"
              :lang="'en'"
              :title="$t('切换到英文界面')"
              @click="switchLocale('en')"
            >English</button>
          </div>
          <p>{{ $t('手工复制，不调用模型 API') }}</p>
          <p class="muted" v-if="appVersion">{{ appVersion }}</p>
        </div>
      </aside>
      <main class="main">
        <projects-page v-if="route.name === 'projects'" />
        <project-page v-else-if="route.name === 'project'" :project-id="route.id" />
        <session-page v-else-if="route.name === 'session'" :session-id="route.id" />
        <history-page v-else-if="route.name === 'history'" />
        <settings-page v-else-if="route.name === 'settings'" />
        <div v-else class="empty">{{ $t('页面不存在。') }} <a href="#/projects">{{ $t('返回工程') }}</a></div>
      </main>

      <div v-if="ui.auto.running" class="auto-banner">
        <span class="auto-banner-spinner"></span>
        <span class="auto-banner-text">{{ $t('正在自动输入 DeepSeek，请不要操作键盘和鼠标…') }}</span>
        <span v-if="ui.auto.message" class="auto-banner-detail">{{ ui.auto.message }}</span>
      </div>

      <div v-if="ui.toast" :class="['toast', 'toast-' + ui.toast.type]">{{ ui.toast.message }}</div>

      <div v-if="ui.confirm" class="modal-backdrop" @click.self="resolveConfirm(false)">
        <div class="modal">
          <div class="modal-head">
            <h2>{{ ui.confirm.title }}</h2>
            <button class="icon-btn" @click="resolveConfirm(false)">×</button>
          </div>
          <p class="confirm-message">{{ ui.confirm.message }}</p>
          <div class="modal-actions">
            <button class="btn" @click="resolveConfirm(false)">{{ ui.confirm.cancelText }}</button>
            <button :class="['btn', ui.confirm.danger ? 'danger' : 'primary']" @click="resolveConfirm(true)">
              {{ ui.confirm.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
};

const app = Vue.createApp(App);
installI18n(app);
// 让 <html lang> 和 document.title 跟随当前语言。
applyDocumentLocale();
app.mount('#app');
