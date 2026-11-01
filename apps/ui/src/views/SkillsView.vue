<template>
  <div class="skills-view">
    <h2>Skill 管理</h2>
    <p class="hint">后端 <code>backend/skills/</code> 目录下 6 个 Skill（含 SKILL.md）。详情按 Markdown 渲染，可加载附属资源。</p>

    <div class="actions">
      <el-button type="primary" @click="openCreate">新建 Skill</el-button>
      <el-button @click="onImport">导入 zip</el-button>
      <input ref="fileInput" type="file" accept=".zip" style="display: none" @change="onFileChosen" />
      <el-button @click="refresh" :loading="loading">刷新</el-button>
      <el-button @click="reload" :loading="reloading">重载目录</el-button>
    </div>

    <el-alert v-if="reloadResult" type="success" :closable="false" style="margin: 12px 0">
      重载完成，共扫描 {{ reloadResult.reloaded }} 个 Skill。
    </el-alert>

    <el-table :data="skills" stripe v-loading="loading" empty-text="暂无 Skill" class="skill-table">
      <el-table-column prop="name" label="名称" width="180">
        <template #default="{ row }">
          {{ row.name }}
          <el-tag v-if="row.source === 'builtin'" size="small" type="info" effect="plain" style="margin-left: 4px">内置</el-tag>
          <el-tag v-else size="small" type="success" effect="plain" style="margin-left: 4px">自定义</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v: boolean) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column prop="skill_md_rel" label="SKILL.md" width="240">
        <template #default="{ row }">
          <code class="path">{{ row.skill_md_rel }}</code>
        </template>
      </el-table-column>
      <el-table-column label="资源" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.resources?.length" type="info">{{ row.resources.length }} 个</el-tag>
          <span v-else style="color: var(--text-faint)">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="330" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="open(row.name)">查看</el-button>
          <el-button size="small" link type="primary" @click="validate(row.name)" :loading="validating === row.name">校验</el-button>
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="primary" :href="exportUrl(row.name)" tag="a">导出</el-button>
          <el-button v-if="row.source === 'custom'" size="small" link type="danger" @click="onDelete(row)">删除</el-button>
          <el-popover v-if="row.resources?.length" trigger="click" placement="left" :width="400">
            <template #reference>
              <el-button size="small" link type="primary">资源 ({{ row.resources.length }})</el-button>
            </template>
            <div v-for="r in row.resources" :key="r" class="resource">
              <code>{{ r }}</code>
              <a :href="resourceUrl(row.name, r)" target="_blank">下载</a>
            </div>
          </el-popover>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog v-model="editDlg.show" :title="editDlg.name ? `编辑 Skill · ${editDlg.name}` : '新建 Skill'" width="640px">
      <el-form label-position="top">
        <el-form-item label="名称（kebab-case）">
          <el-input v-model="editDlg.form.name" :disabled="!!editDlg.name" placeholder="如 my-skill" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editDlg.form.description" placeholder="一句话说明这个 Skill 做什么" />
        </el-form-item>
        <el-form-item label="指令正文（Markdown）">
          <el-input v-model="editDlg.form.content" type="textarea" :rows="10" placeholder="SKILL.md 正文（frontmatter 自动生成）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDlg.show = false">取消</el-button>
        <el-button type="primary" :loading="editDlg.saving" @click="onSaveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawer.show" :title="drawer.title" size="60%">
      <div v-if="drawer.error" class="error">{{ drawer.error }}</div>
      <MarkdownView v-else :text="drawer.content" />
    </el-drawer>

    <el-dialog v-model="validateDlg.show" :title="`校验结果：${validateDlg.name}`" width="500px">
      <el-tag v-if="validateDlg.result?.valid" type="success">通过</el-tag>
      <el-tag v-else type="danger">未通过</el-tag>
      <p style="margin-top: 12px">{{ validateDlg.result?.message }}</p>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  skillsList, skillDetail, skillValidate, skillsReload,
  skillCreate, skillUpdate, skillToggle, skillDelete, skillImport,
} from '@/api'
import { Endpoints } from '@/api/endpoints'
import type { SkillMeta, SkillDetail, ValidationResult } from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'

const skills = ref<SkillMeta[]>([])
const loading = ref(false)
const reloading = ref(false)
const validating = ref<string | null>(null)
const reloadResult = ref<{ reloaded: number; skills: string[] } | null>(null)

const drawer = ref<{ show: boolean; title: string; content: string; error?: string }>({
  show: false, title: '', content: '',
})

const validateDlg = ref<{ show: boolean; name: string; result: ValidationResult | null }>({
  show: false, name: '', result: null,
})

const fileInput = ref<HTMLInputElement>()
const editDlg = ref<{
  show: boolean
  name: string  // 编辑时为目标名（禁改名），新建时为空
  saving: boolean
  form: { name: string; description: string; content: string }
}>({ show: false, name: '', saving: false, form: { name: '', description: '', content: '' } })

function exportUrl(name: string): string {
  return Endpoints.skillExport(name)
}

function openCreate() {
  editDlg.value = { show: true, name: '', saving: false, form: { name: '', description: '', content: '' } }
}

async function openEdit(row: SkillMeta) {
  if (row.source === 'builtin') {
    ElMessage.warning('内置 Skill 为只读，可复制为自定义后修改')
    return
  }
  const detail = await skillDetail(row.name)
  // 去掉 frontmatter，仅编辑正文
  const body = detail.content.split('---').slice(2).join('---').trim()
  editDlg.value = {
    show: true, name: row.name, saving: false,
    form: { name: row.name, description: row.description, content: body },
  }
}

async function onSaveEdit() {
  editDlg.value.saving = true
  try {
    if (editDlg.value.name) {
      await skillUpdate(editDlg.value.name, {
        description: editDlg.value.form.description,
        content: editDlg.value.form.content,
      })
      ElMessage.success('已更新')
    } else {
      await skillCreate(editDlg.value.form)
      ElMessage.success('已创建')
    }
    editDlg.value.show = false
    await refresh()
  } catch (e: unknown) {
    ElMessage.error((e as Error).message)
  } finally {
    editDlg.value.saving = false
  }
}

async function onToggle(row: SkillMeta, enabled: boolean) {
  try {
    await skillToggle(row.name, enabled)
    row.enabled = enabled
  } catch (e: unknown) {
    ElMessage.error((e as Error).message)
  }
}

async function onDelete(row: SkillMeta) {
  await ElMessageBox.confirm(`删除自定义 Skill「${row.name}」？（软删除，可在 .trash 恢复）`, '确认', { type: 'warning' })
  await skillDelete(row.name)
  ElMessage.success('已删除')
  await refresh()
}

function onImport() {
  fileInput.value?.click()
}

async function onFileChosen(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const skill = await skillImport(file)
    ElMessage.success(`已导入：${skill.name}`)
    await refresh()
  } catch (err: unknown) {
    ElMessage.error(`导入失败：${(err as Error).message}`)
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}

onMounted(() => refresh())

async function refresh() {
  loading.value = true
  try { skills.value = (await skillsList()).skills }
  catch (e: unknown) { ElMessage.error(`加载失败：${(e as Error).message}`) }
  finally { loading.value = false }
}

async function reload() {
  reloading.value = true
  try {
    const r = await skillsReload()
    reloadResult.value = r
    await refresh()
  } catch (e: unknown) {
    ElMessage.error(`重载失败：${(e as Error).message}`)
  } finally { reloading.value = false }
}

async function open(name: string) {
  drawer.value = { show: true, title: `Skill · ${name}`, content: '' }
  try {
    const d: SkillDetail = await skillDetail(name)
    drawer.value = { show: true, title: `Skill · ${d.name} · ${d.skill_md_rel}`, content: d.content ?? '' }
  } catch (e: unknown) {
    drawer.value = { show: true, title: `Skill · ${name}`, content: '', error: `加载失败：${(e as Error).message}` }
  }
}

async function validate(name: string) {
  validating.value = name
  try {
    const r = await skillValidate(name)
    validateDlg.value = { show: true, name, result: r }
  } catch (e: unknown) {
    ElMessage.error(`校验失败：${(e as Error).message}`)
  } finally { validating.value = null }
}

function resourceUrl(name: string, resource: string): string {
  return `/api/v1/skills/${encodeURIComponent(name)}/files/${resource.split('/').map(encodeURIComponent).join('/')}`
}
</script>

<style scoped>
.skills-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.path { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.resource { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; }
.resource a { color: var(--accent); margin-left: 8px; }
.error { color: var(--red); padding: 16px; }
</style>