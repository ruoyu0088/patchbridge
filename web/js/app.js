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
      <div v-if="!lines.length" class="muted">没有可显示的 diff</div>
      <div v-for="(line, idx) in lines" :key="idx" :class="['diff-line', 'diff-' + line.type]">
        <span class="diff-ln">{{ line.oldNo }}</span>
        <span class="diff-ln">{{ line.newNo }}</span>
        <span class="diff-code">{{ line.text || ' ' }}</span>
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
name: 新工程
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
        notify('profile 已保存', 'success');
        await this.load();
      } catch (err) {
        this.editor.error = err.message;
      } finally {
        this.saving = false;
      }
    },
    async remove(project) {
      const yes = await confirmDialog({
        title: '删除工程',
        message: `确定删除工程「${project.name}」的 profile 吗？历史会话会保留。`,
        confirmText: '删除',
        danger: true,
      });
      if (!yes) return;
      try {
        await api.delete(`/api/projects/${encodeURIComponent(project.id)}`);
        notify('工程已删除', 'success');
        await this.load();
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
          <h1>工程</h1>
          <p class="muted">每个工程由一个 profile 文件定义根目录和 gitignore 规则。</p>
        </div>
        <button class="btn primary" @click="create">新建工程</button>
      </div>

      <div v-if="error" class="alert error">{{ error }}</div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!projects.length" class="empty">
        还没有工程。点击“新建工程”创建第一个 profile。
      </div>
      <div v-else class="project-grid">
        <article v-for="project in projects" :key="project.id" class="project-card">
          <div class="project-card-head">
            <h2>{{ project.name }}</h2>
            <span v-if="project.root_status && project.root_status.accessible" class="badge ok">可用</span>
            <span v-else class="badge bad">不可用</span>
          </div>
          <div class="mono path-line">{{ project.root || '（未设置根目录）' }}</div>
          <div class="project-meta">
            <span>模式：{{ project.mode === 'include' ? '包含白名单' : '排除' }}</span>
            <span>规则：{{ (project.rules || []).length }}</span>
          </div>
          <div v-if="project.root_status && project.root_status.error" class="alert error small">
            {{ project.root_status.error }}，禁止打包。
          </div>
          <div v-if="project.error" class="alert error small">{{ project.error }}</div>
          <div v-if="project.warnings && project.warnings.length" class="warnings small">
            <div v-for="(warning, idx) in project.warnings" :key="idx">• {{ warning }}</div>
          </div>
          <div class="card-actions">
            <button class="btn primary" :disabled="!project.root_status || !project.root_status.accessible" @click="open(project)">
              打开
            </button>
            <button class="btn" @click="edit(project)">编辑 profile</button>
            <button class="btn danger-text" @click="remove(project)">删除</button>
          </div>
        </article>
      </div>

      <div v-if="editor" class="modal-backdrop" @click.self="editor = null">
        <div class="modal wide">
          <div class="modal-head">
            <h2>{{ editor.mode === 'create' ? '新建 profile' : '编辑 profile' }}</h2>
            <button class="icon-btn" @click="editor = null">×</button>
          </div>
          <p class="muted">
            纯文本 profile：root 必须是绝对路径；mode 为 exclude 或 include；
            [rules] 使用 gitignore 语法，支持 ! 取反。
          </p>
          <textarea v-model="editor.raw" class="code-editor profile-editor" spellcheck="false"></textarea>
          <div v-if="editor.error" class="alert error">{{ editor.error }}</div>
          <div class="modal-actions">
            <button class="btn" @click="editor = null">取消</button>
            <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
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
      project: null,
      files: [],
      summary: null,
      loading: true,
      error: '',
      query: '',
      selected: {},
      requirement: '',
      packing: false,
      packResult: null,
      bundleText: '',
      bundlePreviewOpen: false,
      bundleLoading: false,
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
  },
  mounted() {
    this.load();
  },
  watch: {
    projectId() {
      this.load();
    },
  },
  methods: {
    formatBytes,
    async load() {
      this.loading = true;
      this.error = '';
      this.selected = {};
      this.packResult = null;
      this.files = [];
      this.summary = null;
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
        const treeData = await api.get(`/api/projects/${encodeURIComponent(this.projectId)}/tree`);
        this.files = treeData.files || [];
        this.summary = treeData.summary || null;
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
    },
    clearAll() {
      this.selected = {};
    },
    async pack() {
      if (!this.accessible) return;
      if (!this.requirement.trim()) {
        notify('请先输入需求', 'error');
        return;
      }
      if (!this.selectedPaths.length) {
        notify('请至少勾选一个文件', 'error');
        return;
      }
      this.packing = true;
      try {
        this.packResult = await api.post(
          `/api/projects/${encodeURIComponent(this.projectId)}/pack`,
          { requirement: this.requirement, files: this.selectedPaths },
        );
        this.bundleText = '';
        this.bundlePreviewOpen = false;
        notify('打包完成。现在可以把完整文本或文件路径交给 Web AI。', 'success');
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.packing = false;
      }
    },
    async copyBundleText() {
      try {
        const text = this.bundleText || (await api.text(`/api/sessions/${this.packResult.session_id}/bundle`));
        this.bundleText = text;
        await copyText(text, '打包全文');
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async copyBundlePath() {
      if (!this.packResult || !this.packResult.bundle_path) return;
      await copyText(this.packResult.bundle_path, '打包文件路径');
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
          <button class="btn link" @click="back">← 工程列表</button>
          <h1>{{ project ? project.name : '工程' }}</h1>
          <div v-if="project" class="mono path-line">{{ project.root }}</div>
        </div>
        <div v-if="summary" class="summary-pills">
          <span class="pill">{{ summary.count }} 个可选文件</span>
          <span class="pill">{{ formatBytes(summary.bytes) }}</span>
          <span v-if="summary.skipped.large" class="pill muted">大文件 {{ summary.skipped.large }}</span>
          <span v-if="summary.skipped.binary" class="pill muted">二进制 {{ summary.skipped.binary }}</span>
        </div>
      </div>

      <div v-if="loading" class="empty">加载文件树…</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <div v-else-if="!accessible" class="alert error">
        根目录不可访问，禁止打包。请编辑 profile 修正 root。
      </div>
      <div v-else class="workspace-grid">
        <section class="panel tree-panel">
          <div class="panel-head">
            <h2>文件树</h2>
            <div class="small-actions">
              <button class="btn tiny" @click="selectAll">全选当前</button>
              <button class="btn tiny" @click="clearAll">清空</button>
            </div>
          </div>
          <input v-model="query" class="search-input" placeholder="按路径搜索…" />
          <div class="tree-scroll">
            <div v-if="!filteredFiles.length" class="muted pad">没有匹配的文件</div>
            <file-tree-node
              v-for="node in tree"
              :key="node.path"
              :node="node"
              :selected="selected"
              @toggle="toggleNode"
            />
          </div>
          <div class="selection-bar">
            已选 <strong>{{ selectedCount }}</strong> 个文件，共 {{ formatBytes(selectedBytes) }}
          </div>
        </section>

        <section class="panel compose-panel">
          <div class="panel-head"><h2>需求与打包</h2></div>
          <label class="field-label">修改需求</label>
          <textarea
            v-model="requirement"
            class="requirement-editor"
            placeholder="说明要改什么、期望的行为、限制和验收标准…"
          ></textarea>
          <div class="compose-actions">
            <button class="btn primary" :disabled="packing" @click="pack">
              {{ packing ? '打包中…' : '生成打包文本' }}
            </button>
            <span class="muted">打包前会记录每个文件的 sha256 快照。</span>
          </div>

          <div v-if="packResult" class="bundle-result">
            <div class="bundle-result-head">
              <h3>打包完成</h3>
              <span class="badge ok">{{ packResult.file_count }} 个文件</span>
              <span class="pill">{{ formatBytes(packResult.bundle_size) }}</span>
              <span class="pill">约 {{ packResult.token_estimate }} tokens</span>
            </div>
            <p class="muted">
              两种方式任选其一交给 Web AI：复制完整文本，或复制下面的文件路径后在本地打开/上传文件。
            </p>
            <div class="path-copy-row">
              <code class="mono path-box">{{ packResult.bundle_path }}</code>
              <button class="btn" @click="copyBundlePath">复制文件路径</button>
            </div>
            <div class="button-row">
              <button class="btn primary" @click="copyBundleText">复制完整文本</button>
              <button class="btn" @click="downloadBundle">下载文本文件</button>
              <button class="btn" @click="toggleBundlePreview">
                {{ bundlePreviewOpen ? '收起预览' : '预览文本' }}
              </button>
              <button class="btn accent" @click="openSession">打开审阅页 →</button>
            </div>
            <div v-if="bundlePreviewOpen" class="bundle-preview">
              <div v-if="bundleLoading" class="muted">读取中…</div>
              <pre v-else>{{ bundleText }}</pre>
            </div>
            <p class="hint">
              打包文本保存于会话 <code>{{ packResult.session_id }}</code>，之后可在历史中重新载入。
            </p>
          </div>
        </section>
      </div>
    </div>
  `,
};

const SessionPage = {
  name: 'SessionPage',
  components: { DiffView },
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
      bundleText: '',
      bundleLoading: false,
      disk: null,
      diskLoading: false,
      busy: false,
      confirmApply: null,
      hashConfirmChecked: {},
      applyResult: null,
      reverting: false,
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
    bundlePath() {
      return (this.details && this.details.bundle_path) || '';
    },
    archivePath() {
      return (this.details && this.details.archive_path) || '';
    },
  },
  mounted() {
    this.load();
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
      try {
        this.details = await api.get(`/api/sessions/${encodeURIComponent(this.sessionId)}`);
        this.answerText = this.details.answer || '';
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
        notify('没有待应用的补丁', 'info');
        return;
      }
      const data = await this.preview(true, pending);
      if (data) {
        notify(data.ok ? '全部补丁通过 dry-run' : `有 ${data.conflicts} 个补丁存在冲突`, data.ok ? 'success' : 'error');
      }
    },
    async dryOne(patch) {
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/dry-run`, {
          patch_ids: [patch.id],
          persist: true,
        });
        for (const item of data.results || []) this.statuses[item.patch_id] = item;
        notify(data.ok ? `${patch.path} 可应用` : `${patch.path} 无法应用`, data.ok ? 'success' : 'error');
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    statusFor(patch) {
      return this.statuses[patch.id] || null;
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
    async applySelected() {
      if (!this.selectedIds.length) {
        notify('请至少勾选一个补丁', 'error');
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
        notify('补丁已应用，备份已写入', 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'hash_changed') {
          this.confirmApply = { ids, paths: (err.details && err.details.paths) || [] };
          this.hashConfirmChecked = {};
          notify('有文件 hash 变化，需要逐项确认', 'error');
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
        notify('请确认所有 hash 变化的文件', 'error');
        return;
      }
      this.doApply(this.confirmApply.ids, this.confirmApply.paths);
    },
    async revert() {
      const yes = await confirmDialog({
        title: '撤回最近一次应用',
        message: '撤回会按备份恢复本批次修改过的文件，并删除新增文件。是否继续？',
        confirmText: '撤回',
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
        notify('已撤回最近一次应用', 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'revert_hash_changed') {
          const paths = (err.details && err.details.paths) || [];
          const yes = await confirmDialog({
            title: '文件在应用后又被改过',
            message: `以下文件与“应用后”不一致：\\n${paths.join('\\n')}\\n\\n确认仍按备份恢复吗？这会覆盖这些外部修改。`,
            confirmText: '仍然撤回',
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
    startEditPatch(patch) {
      this.editingPatchId = patch.id;
      this.patchDraft = patch.content || '';
    },
    cancelEditPatch() {
      this.editingPatchId = null;
      this.patchDraft = '';
    },
    async savePatch(patch) {
      try {
        await api.put(`/api/sessions/${this.sessionId}/patches/${patch.id}`, {
          content: this.patchDraft,
        });
        this.editingPatchId = null;
        this.patchDraft = '';
        notify('补丁已更新，正在重新检查', 'success');
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
        notify('commit 文本已保存', 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async submitAnswer() {
      if (!this.answerDraft.trim()) {
        notify('请先粘贴 AI 回答', 'error');
        return;
      }
      this.busy = true;
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/answer`, {
          answer: this.answerDraft,
        });
        const count = (data.parsed && data.parsed.patches.length) || 0;
        this.answerDraft = '';
        notify(`解析完成，提取到 ${count} 个文件补丁`, count ? 'success' : 'error');
        this.tab = 'review';
        await this.load();
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
      if (text) await copyText(text, '打包全文');
    },
    async copyBundlePath() {
      if (!this.bundlePath) {
        notify('归档会话没有可直接复制的未压缩文件路径，请先重新载入', 'error');
        return;
      }
      await copyText(this.bundlePath, '打包文件路径');
    },
    async copyCommit() {
      const text = (this.parsed && this.parsed.commit_message) || '';
      if (text) await copyText(text, 'commit 建议');
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
        title: '归档会话',
        message: '归档后会话目录会变成 zip 压缩包，列表仍可见。若仍有未撤回的应用，撤回时会先解压。',
        confirmText: '归档',
      });
      if (!yes) return;
      try {
        await api.post(`/api/sessions/${this.sessionId}/archive`);
        notify('会话已归档', 'success');
        await this.load();
      } catch (err) {
        if (err.code === 'archive_active_apply') {
          const force = await confirmDialog({
            title: '仍有未撤回的补丁应用',
            message: '归档后如需撤回，PatchBridge 会先自动解压。确认归档吗？',
            confirmText: '仍然归档',
            danger: true,
          });
          if (!force) return;
          try {
            await api.post(`/api/sessions/${this.sessionId}/archive`, {
              confirm_active_apply: true,
            });
            notify('会话已归档', 'success');
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
        title: '删除会话',
        message: '删除会话不会还原磁盘文件。确定删除这条历史记录吗？',
        confirmText: '删除',
        danger: true,
      });
      if (!yes) return;
      try {
        await api.delete(`/api/sessions/${this.sessionId}`);
        notify('会话已删除', 'success');
        location.hash = '#/history';
      } catch (err) {
        if (err.code === 'active_apply') {
          const force = await confirmDialog({
            title: '仍有未撤回的补丁应用',
            message: '删除会话不会影响磁盘上的代码，也不会自动撤回补丁。确认删除历史记录吗？',
            confirmText: '仍然删除',
            danger: true,
          });
          if (!force) return;
          try {
            await api.delete(`/api/sessions/${this.sessionId}?confirm_active=true`);
            notify('会话已删除', 'success');
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
        title: '标记为已放弃',
        message: '标记后会话状态变为“已放弃”，可用于自动归档。不会修改磁盘文件。',
        confirmText: '标记放弃',
      });
      if (!yes) return;
      try {
        await api.post(`/api/sessions/${this.sessionId}/abandon`);
        notify('会话已标记为放弃', 'success');
        await this.load();
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    async reloadSession() {
      try {
        const data = await api.post(`/api/sessions/${this.sessionId}/reload`);
        notify('已生成新会话，并重新校验 hash', 'success');
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
      <div v-if="loading" class="empty">加载会话…</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <template v-else>
        <div class="page-header session-header">
          <div>
            <button class="btn link" @click="back">← 返回</button>
            <h1>{{ meta.title }}</h1>
            <div class="meta-row">
              <span class="mono">{{ sessionId }}</span>
              <span class="badge" :class="'status-' + status">{{ statusText(status) }}</span>
              <span v-if="archived" class="badge muted">已归档</span>
              <span v-if="meta.reloaded_from" class="badge muted">重新载入</span>
            </div>
          </div>
          <div class="button-row wrap">
            <button class="btn" @click="reloadSession">重新载入</button>
            <button class="btn" @click="archiveSession">归档</button>
            <a class="btn" :href="exportUrl('md')">导出文档</a>
            <a class="btn" :href="exportUrl('patch')">导出 patch</a>
            <button class="btn danger-text" @click="deleteSession">删除</button>
          </div>
        </div>

        <div v-if="archived" class="alert info">
          该会话已归档。详情可直接读取；应用、撤回、重新载入等操作会自动解压。
        </div>

        <div class="tabs">
          <button :class="['tab', tab === 'review' ? 'active' : '']" @click="tab = 'review'">补丁审阅</button>
          <button :class="['tab', tab === 'bundle' ? 'active' : '']" @click="tab = 'bundle'">打包文本</button>
          <button :class="['tab', tab === 'answer' ? 'active' : '']" @click="tab = 'answer'">AI 回答</button>
          <button :class="['tab', tab === 'events' ? 'active' : '']" @click="tab = 'events'">事件</button>
          <button :class="['tab', tab === 'disk' ? 'active' : '']" @click="tab = 'disk'; !disk && loadDisk()">磁盘差异</button>
        </div>

        <section v-if="tab === 'review'" class="review-layout">
          <div class="review-main">
            <div v-if="!parsed" class="panel answer-panel">
              <h2>粘贴 AI 的完整回答</h2>
              <p class="muted">
                把 Web AI 输出的所有内容原样粘贴到这里。PatchBridge 会自动寻找修改说明、commit 建议和 unified diff。
              </p>
              <textarea
                v-model="answerDraft"
                class="answer-editor"
                placeholder="粘贴 AI 回答全文…"
              ></textarea>
              <button class="btn primary" :disabled="busy" @click="submitAnswer">
                {{ busy ? '解析中…' : '解析回答并提取补丁' }}
              </button>
            </div>

            <template v-else>
              <div class="panel">
                <div class="panel-head">
                  <h2>修改说明</h2>
                </div>
                <pre class="prose">{{ parsed.explanation || '（未提取到修改说明）' }}</pre>
              </div>

              <div class="panel">
                <div class="panel-head">
                  <h2>Commit 建议</h2>
                  <div class="small-actions">
                    <button class="btn tiny" @click="copyCommit">复制</button>
                    <button v-if="!patchLocked" class="btn tiny" @click="startEditCommit">编辑</button>
                  </div>
                </div>
                <div v-if="!editingCommit" class="commit-box mono">{{ parsed.commit_message || '（未提取到 commit 建议）' }}</div>
                <div v-else>
                  <textarea v-model="commitDraft" class="commit-editor" rows="3"></textarea>
                  <div class="button-row">
                    <button class="btn primary" @click="saveCommit">保存</button>
                    <button class="btn" @click="editingCommit = false">取消</button>
                  </div>
                </div>
              </div>

              <div v-if="warnings.length" class="alert warning">
                <strong>解析警告</strong>
                <div v-for="(warning, idx) in warnings" :key="idx">• {{ warning }}</div>
              </div>

              <div v-if="applyResult" class="alert success">
                已应用 {{ applyResult.paths.length }} 个文件：{{ applyResult.paths.join('、') }}
              </div>

              <div class="patch-toolbar">
                <div>
                  <button class="btn tiny" @click="toggleAll">反选未应用</button>
                  <span class="muted">已选 {{ selectedIds.length }} / {{ patches.length }}</span>
                </div>
                <div class="button-row">
                  <button class="btn" @click="dryAll">全部 dry-run</button>
                  <button class="btn primary" :disabled="busy || !selectedIds.length" @click="applySelected">
                    应用选中补丁
                  </button>
                  <button v-if="hasUnrevertedApply" class="btn danger" :disabled="reverting" @click="revert">
                    {{ reverting ? '撤回中…' : '撤回最近一次应用' }}
                  </button>
                </div>
              </div>

              <div v-if="patchLocked" class="alert info">
                本会话已经应用过补丁，补丁与 commit 文本已锁定。未应用的文件仍可应用；如需修改补丁，请使用“重新载入”生成新会话。
              </div>

              <article v-for="patch in patches" :key="patch.id" class="patch-card">
                <div class="patch-head">
                  <input
                    type="checkbox"
                    v-model="selected[patch.id]"
                    :disabled="isApplied(patch)"
                  />
                  <div class="patch-title mono">{{ patch.path }}</div>
                  <span v-if="patch.new_file" class="badge new">新增</span>
                  <span v-if="isApplied(patch)" class="badge ok">已应用</span>
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
                    <span class="badge muted">p{{ patch.p_level || 1 }}</span>
                    <span v-if="statusFor(patch) && statusFor(patch).reason" class="badge bad">
                      {{ statusFor(patch).reason }}
                    </span>
                  </template>
                  <template v-else>
                    <span class="badge ok">本批次已应用</span>
                    <span class="badge muted">p{{ patch.p_level || 1 }}</span>
                  </template>
                </div>
                <div v-if="statusFor(patch) && statusFor(patch).warnings.length" class="warnings small">
                  <div v-for="(warning, idx) in statusFor(patch).warnings" :key="idx">• {{ warning }}</div>
                </div>

                <div v-if="editingPatchId === patch.id" class="patch-edit">
                  <textarea v-model="patchDraft" class="code-editor" spellcheck="false"></textarea>
                  <div class="button-row">
                    <button class="btn primary" @click="savePatch(patch)">保存并重新检查</button>
                    <button class="btn" @click="cancelEditPatch">取消</button>
                  </div>
                </div>
                <diff-view v-else-if="openPatches[patch.id]" :content="patch.content" />

                <div class="patch-actions">
                  <button class="btn tiny" @click="dryOne(patch)">单文件 dry-run</button>
                  <button
                    v-if="!patchLocked && !isApplied(patch)"
                    class="btn tiny"
                    @click="startEditPatch(patch)"
                  >编辑补丁</button>
                </div>
              </article>
            </template>
          </div>

          <aside class="review-side">
            <div class="panel side-panel">
              <h3>会话信息</h3>
              <dl class="meta-list">
                <dt>工程</dt><dd>{{ meta.project_name }}</dd>
                <dt>根目录</dt><dd class="mono break">{{ meta.root }}</dd>
                <dt>创建</dt><dd>{{ shortDate(meta.created_at) }}</dd>
                <dt>文件数</dt><dd>{{ meta.file_count }}</dd>
                <dt>大小</dt><dd>{{ formatBytes(meta.total_bytes) }}</dd>
              </dl>
            </div>
            <div class="panel side-panel">
              <h3>交给 AI 的文本</h3>
              <p class="muted small">可以复制全文，或复制文件完整路径。</p>
              <div class="path-box mono break">{{ bundlePath || '（已归档）' }}</div>
              <div class="button-row wrap">
                <button class="btn tiny" @click="copyBundlePath">复制文件路径</button>
                <button class="btn tiny" @click="copyBundleText">复制全文</button>
              </div>
            </div>
            <div class="panel side-panel">
              <h3>快捷操作</h3>
              <div class="button-row wrap">
                <button class="btn tiny" @click="tab = 'answer'">替换 AI 回答</button>
                <button class="btn tiny" @click="tab = 'events'">查看事件</button>
                <button class="btn tiny" @click="tab = 'disk'">比较磁盘</button>
                <button
                  v-if="!details.has_any_apply && status !== 'abandoned'"
                  class="btn tiny"
                  @click="abandonSession"
                >标记为已放弃</button>
              </div>
            </div>
          </aside>
        </section>

        <section v-if="tab === 'bundle'" class="panel">
          <div class="panel-head">
            <h2>打包文本</h2>
            <div class="button-row">
              <button class="btn" @click="copyBundlePath">复制文件路径</button>
              <button class="btn primary" @click="copyBundleText">复制全文</button>
              <a class="btn" :href="'/api/sessions/' + sessionId + '/bundle'">下载</a>
            </div>
          </div>
          <div class="path-copy-row">
            <code class="mono path-box break">{{ bundlePath || '（已归档，压缩包：' + archivePath + '）' }}</code>
          </div>
          <div v-if="bundleLoading" class="muted">读取中…</div>
          <pre v-else-if="bundleText" class="bundle-full">{{ bundleText }}</pre>
          <div v-else class="empty">
            <button class="btn primary" @click="loadBundleText">加载 / 复制完整文本</button>
          </div>
        </section>

        <section v-if="tab === 'answer'" class="panel">
          <div class="panel-head">
            <h2>AI 回答原文</h2>
          </div>
          <div v-if="!patchLocked" class="answer-replace">
            <p class="muted">重新粘贴一份完整回答会覆盖当前解析结果。已应用的会话不能重新解析。</p>
            <textarea v-model="answerDraft" class="answer-editor" placeholder="粘贴新的 AI 回答全文…"></textarea>
            <button class="btn primary" :disabled="busy" @click="submitAnswer">重新解析</button>
          </div>
          <pre class="prose answer-raw">{{ answerText || '（还没有保存 AI 回答）' }}</pre>
        </section>

        <section v-if="tab === 'events'" class="panel">
          <div class="panel-head"><h2>操作事件</h2></div>
          <div v-if="!events.length" class="muted">暂无事件</div>
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
            <h2>“应用后”与当前磁盘的差异</h2>
            <button class="btn" :disabled="diskLoading" @click="loadDisk">
              {{ diskLoading ? '比较中…' : '重新比较' }}
            </button>
          </div>
          <div v-if="!disk" class="muted">点击“重新比较”生成差异。</div>
          <div v-else-if="!disk.available" class="alert info">{{ disk.message }}</div>
          <div v-else>
            <div class="alert" :class="disk.files.length ? 'warning' : 'success'">{{ disk.message }}</div>
            <div v-for="file in disk.files" :key="file.path" class="disk-file">
              <h3 class="mono">{{ file.path }} <span class="badge">{{ file.status }}</span></h3>
              <pre class="prose">{{ file.diff || '（无法生成文本 diff）' }}</pre>
            </div>
          </div>
        </section>

        <div v-if="confirmApply" class="modal-backdrop" @click.self="confirmApply = null">
          <div class="modal">
            <div class="modal-head">
              <h2>确认 hash 变化</h2>
              <button class="icon-btn" @click="confirmApply = null">×</button>
            </div>
            <p class="warning-text">
              以下文件在打包后被外部修改。应用补丁会以当前磁盘内容为基准；请确认你了解这一点。
            </p>
            <label v-for="path in confirmApply.paths" :key="path" class="check-row">
              <input type="checkbox" v-model="hashConfirmChecked[path]" />
              <span class="mono">{{ path }}</span>
            </label>
            <div class="modal-actions">
              <button class="btn" @click="confirmApply = null">取消</button>
              <button class="btn danger" :disabled="busy" @click="confirmHashApply">确认并应用</button>
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
        notify('索引已重建', 'success');
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
          <h1>会话历史</h1>
          <p class="muted">所有会话均以纯文本保存，可按工程、状态、日期筛选。</p>
        </div>
        <button v-if="index && index.status && index.status.stale" class="btn accent" @click="rebuild">
          索引不一致，重建
        </button>
      </div>

      <div v-if="index && index.rebuilt" class="alert info">检测到会话目录与索引不一致，已自动重建索引。</div>

      <div class="filter-bar">
        <select v-model="filters.project_id" @change="load">
          <option value="">全部工程</option>
          <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
        <select v-model="filters.status" @change="load">
          <option value="">全部状态</option>
          <option value="packed">待 AI 回答</option>
          <option value="parsed">已解析</option>
          <option value="applied">已应用</option>
          <option value="reverted">已撤回</option>
          <option value="abandoned">已放弃</option>
        </select>
        <select v-model="filters.archived" @change="load">
          <option value="">全部存储</option>
          <option value="false">未归档</option>
          <option value="true">已归档</option>
        </select>
        <input v-model="filters.q" placeholder="搜索标题 / 工程 / ID" @keyup.enter="load" />
        <input v-model="filters.date_from" type="date" @change="load" />
        <input v-model="filters.date_to" type="date" @change="load" />
        <button class="btn" @click="load">刷新</button>
      </div>

      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!sessions.length" class="empty">没有符合条件的会话。</div>
      <div v-else class="session-list">
        <article v-for="session in sessions" :key="session.id" class="session-row" @click="open(session)">
          <div class="session-main">
            <div class="session-title-line">
              <h3>{{ session.title }}</h3>
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
            <span>{{ session.file_count }} 文件</span>
            <span>{{ formatBytes(session.bundle_bytes) }}</span>
            <span>{{ session.patches }} 补丁</span>
            <span v-if="session.warnings" class="badge warning">{{ session.warnings }} 警告</span>
          </div>
        </article>
      </div>

      <details v-if="index" class="index-details">
        <summary>索引状态</summary>
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
        notify('设置已保存', 'success');
      } catch (err) {
        notify(err.message, 'error');
      } finally {
        this.saving = false;
      }
    },
    async reloadMeta() {
      try {
        const meta = await api.get('/api/meta');
        this.meta = meta;
      } catch (err) {
        notify(err.message, 'error');
      }
    },
  },
  template: `
    <div class="page narrow">
      <div class="page-header">
        <div><h1>设置</h1><p class="muted">这些设置对全部工程生效。</p></div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="error" class="alert error">{{ error }}</div>
      <div v-else class="panel settings-panel">
        <label class="field-label">大文件阈值（MB）</label>
        <input v-model.number="largeMb" type="number" min="0.1" step="0.1" />
        <p class="hint">超过该大小的文件默认不进入文件树，也不会被选中。</p>

        <label class="field-label">自动归档</label>
        <label class="check-row">
          <input type="checkbox" v-model="settings.auto_archive_enabled" />
          <span>启用自动归档（默认关闭）</span>
        </label>
        <label class="field-label">自动归档天数</label>
        <input v-model.number="settings.auto_archive_days" type="number" min="1" />
        <p class="hint">
          只归档没有未撤回 apply、且状态为已撤回或已放弃、超过指定天数的会话。
        </p>

        <label class="field-label">提示词模板路径</label>
        <input v-model="settings.prompt_template_path" placeholder="留空使用内置模板" />
        <div class="path-copy-row" v-if="meta">
          <code class="mono path-box break">{{ meta.prompt_path_resolved }}</code>
          <span class="badge" :class="meta.prompt_exists ? 'ok' : 'bad'">
            {{ meta.prompt_exists ? '存在' : '不存在' }}
          </span>
          <button class="btn tiny" @click="reloadMeta">检查</button>
        </div>
        <p class="hint">
          模板支持 <code v-pre>{{PROJECT_NAME}}</code>、<code v-pre>{{FILE_COUNT}}</code>、
          <code v-pre>{{TOTAL_BYTES}}</code> 等占位符。
        </p>

        <label class="field-label">备份保留天数</label>
        <input v-model.number="settings.backup_retention_days" type="number" min="1" />
        <p class="hint">清理备份时不会删除仍有未撤回 apply 的备份。</p>

        <label class="field-label">最大扫描文件数</label>
        <input v-model.number="settings.max_files" type="number" min="1" />
        <label class="field-label">单次打包大小上限（字节）</label>
        <input v-model.number="settings.max_bundle_bytes" type="number" min="1024" />

        <div class="button-row">
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存设置' }}</button>
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
    };
  },
  computed: {
    sessionId() {
      return this.route.id;
    },
  },
  mounted() {
    window.addEventListener('hashchange', this.updateRoute);
    this.updateRoute();
  },
  methods: {
    updateRoute() {
      const hash = location.hash.replace(/^#/, '') || '/projects';
      const parts = hash.split('/').filter(Boolean);
      const name = parts[0] || 'projects';
      this.route = {
        name,
        id: parts[1] ? decodeURIComponent(parts[1]) : '',
      };
      this.answerText = '';
    },
    go(path) {
      location.hash = path;
    },
    resolveConfirm(value) {
      closeConfirm(value);
    },
  },
  template: `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand" @click="go('#/projects')">
          <span class="brand-mark">PB</span>
          <div>
            <strong>PatchBridge</strong>
            <small>Web AI → 安全补丁</small>
          </div>
        </div>
        <nav>
          <a data-short="工程" href="#/projects" :class="['nav-item', route.name === 'projects' || route.name === 'project' ? 'active' : '']">工程</a>
          <a data-short="历史" href="#/history" :class="['nav-item', route.name === 'history' || route.name === 'session' ? 'active' : '']">历史会话</a>
          <a data-short="设置" href="#/settings" :class="['nav-item', route.name === 'settings' ? 'active' : '']">设置</a>
        </nav>
        <div class="sidebar-foot">
          <p>手工复制，不调用模型 API</p>
          <p class="muted">v0.1.0</p>
        </div>
      </aside>
      <main class="main">
        <projects-page v-if="route.name === 'projects'" />
        <project-page v-else-if="route.name === 'project'" :project-id="route.id" />
        <session-page v-else-if="route.name === 'session'" :session-id="route.id" />
        <history-page v-else-if="route.name === 'history'" />
        <settings-page v-else-if="route.name === 'settings'" />
        <div v-else class="empty">页面不存在。 <a href="#/projects">返回工程</a></div>
      </main>

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

Vue.createApp(App).mount('#app');
