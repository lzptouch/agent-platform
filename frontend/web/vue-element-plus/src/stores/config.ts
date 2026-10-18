/**
 * 全局配置 / 能力探测 / 工具链开关 store
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentModels, agentStatus, skillsList, mcpList } from '@/api'
import type { ModelsResp, SkillMeta, McpServerInfo } from '@/api/types'

export const useConfigStore = defineStore('config', () => {
  const ready = ref(false)
  const banner = ref<string>('')

  // 模型 / Skill / MCP
  const models = ref<ModelsResp | null>(null)
  const model = ref<string>('')
  const skills = ref<SkillMeta[]>([])
  const mcpServers = ref<McpServerInfo[]>([])

  // 工具链开关
  const enableMcp = ref(false)
  const enableRag = ref(true)
  const enableWeb = ref(false)
  const enableReflection = ref(false)
  const selectedServers = ref<string[]>(['weather'])

  // Skill 多选（默认全选；持久化到 localStorage）
  const selectedSkills = ref<string[]>([])
  const SKILL_KEY = 'ap-vue-ep-skills'
  try {
    const raw = localStorage.getItem(SKILL_KEY)
    if (raw) {
      const saved = JSON.parse(raw) as string[]
      if (Array.isArray(saved)) selectedSkills.value = saved
    }
  } catch { /* */ }

  function persistSkills() {
    try { localStorage.setItem(SKILL_KEY, JSON.stringify(selectedSkills.value)) } catch { /* */ }
  }

  async function init() {
    ready.value = false
    banner.value = ''
    try {
      const [modelsRes, statusRes, skillsRes, mcpRes] = await Promise.all([
        agentModels(),
        agentStatus(),
        skillsList(),
        mcpList(),
      ])
      models.value = modelsRes
      model.value = modelsRes.default_model
      skills.value = skillsRes.skills
      mcpServers.value = mcpRes.servers

      // 首次访问：默认全选 Skill
      if (selectedSkills.value.length === 0) {
        selectedSkills.value = skillsRes.skills.map(s => s.name)
      } else {
        // 过滤掉已不存在的 Skill
        const valid = new Set(skillsRes.skills.map(s => s.name))
        selectedSkills.value = selectedSkills.value.filter(n => valid.has(n))
      }

      if (!statusRes.api_key_configured) {
        banner.value = '未检测到 DASHSCOPE_API_KEY：请在 backend/.env 中配置后重启后端。'
      }
    } catch (e: unknown) {
      banner.value = `初始化失败：${(e as Error).message ?? e}`
    } finally {
      ready.value = true
    }
  }

  return {
    ready, banner,
    models, model, skills, mcpServers,
    enableMcp, enableRag, enableWeb, enableReflection, selectedServers,
    selectedSkills,
    persistSkills, init,
  }
})