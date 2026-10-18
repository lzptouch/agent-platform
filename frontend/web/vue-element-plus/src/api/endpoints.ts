/**
 * 端点常量（统一路径），由 client/sse 引用，避免散落字符串。
 *
 * 所有路径以 /api/v1 开头。方法见后端 app/api/v1/router.py 与各子文件。
 */

export const API_BASE = '/api/v1'

export const Endpoints = {
  // System
  health: `${API_BASE}/health`,
  docsInfo: '/docs-info',

  // Agent
  agentModels: `${API_BASE}/agent/models`,
  agentStatus: `${API_BASE}/agent/status`,
  agentRun:       `${API_BASE}/agent/run`,
  agentRunSync:   `${API_BASE}/agent/run/sync`,
  agentChat:      `${API_BASE}/agent/chat`,

  // Skills
  skillsList:    `${API_BASE}/skills`,
  skillsReload:  `${API_BASE}/skills/reload`,
  skillDetail:   (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}`,
  skillValidate: (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}/validate`,
  skillResource: (name: string, resourcePath: string) =>
    `${API_BASE}/skills/${encodeURIComponent(name)}/files/${resourcePath.split('/').map(encodeURIComponent).join('/')}`,

  // Files
  filesList:   `${API_BASE}/files`,
  filesUpload: `${API_BASE}/files/upload`,
  file:        (name: string) => `${API_BASE}/files/${encodeURIComponent(name)}`,

  // MCP
  mcpList:        `${API_BASE}/mcp_servers`,
  mcpReload:      `${API_BASE}/mcp_servers/reload`,
  mcpDetail:      (name: string) => `${API_BASE}/mcp_servers/${encodeURIComponent(name)}`,
  mcpStart:       (name: string) => `${API_BASE}/mcp_servers/${encodeURIComponent(name)}/start`,
  mcpStop:        (name: string) => `${API_BASE}/mcp_servers/${encodeURIComponent(name)}/stop`,
  mcpTools:       (name: string) => `${API_BASE}/mcp_servers/${encodeURIComponent(name)}/tools`,
  mcpCall:        (name: string) => `${API_BASE}/mcp_servers/${encodeURIComponent(name)}/call`,

  // RAG
  ragQuery:    `${API_BASE}/rag/query`,
  ragRetrieval:`${API_BASE}/rag/retrieval`,
  ragIngest:   `${API_BASE}/rag/ingest`,           // ⚠️ recreate 是 query 参数
  ragStats:    `${API_BASE}/rag/stats`,

  // Web Research
  webResearch:        `${API_BASE}/web_research/research`,
  webResearchStatus:  `${API_BASE}/web_research/status`,

  // Deep Research
  researchHealth: `${API_BASE}/research/health`,
  researchSubmit: `${API_BASE}/research`,
  researchList:   `${API_BASE}/research`,
  researchStatus: (taskId: string) => `${API_BASE}/research/${taskId}`,
  researchResult: (taskId: string) => `${API_BASE}/research/${taskId}/result`,
  researchStream: (taskId: string) => `${API_BASE}/research/${taskId}/stream`,
  researchDelete: (taskId: string) => `${API_BASE}/research/${taskId}`,

  // Sessions（对话/工作双模式）
  sessions:      `${API_BASE}/sessions`,
  session:       (id: string) => `${API_BASE}/sessions/${id}`,

  // Runs（运行账本 / Plan 审批 / 事件回放）
  run:           (id: string) => `${API_BASE}/runs/${id}`,
  runEvents:     (id: string) => `${API_BASE}/runs/${id}/events`,
  runStream:     (id: string) => `${API_BASE}/runs/${id}/stream`,
  runApprove:    (id: string) => `${API_BASE}/agent/runs/${id}/approve`,
  runReject:     (id: string) => `${API_BASE}/agent/runs/${id}/reject`,

  // Teams（Skill 团队）
  teams:         `${API_BASE}/teams`,
  team:          (id: string) => `${API_BASE}/teams/${id}`,
  teamToggle:    (id: string) => `${API_BASE}/teams/${id}/toggle`,
  teamResolve:   (id: string) => `${API_BASE}/teams/${id}/resolve`,

  // Schedules（定时任务）
  schedules:     `${API_BASE}/schedules`,
  schedule:      (id: string) => `${API_BASE}/schedules/${id}`,
  scheduleToggle:(id: string) => `${API_BASE}/schedules/${id}/toggle`,
  scheduleRunNow:(id: string) => `${API_BASE}/schedules/${id}/run-now`,
  scheduleRuns:  (id: string) => `${API_BASE}/schedules/${id}/runs`,
  scheduleValidate: `${API_BASE}/schedules/validate`,
  scheduleHealth:   `${API_BASE}/schedules/health`,

  // Skill 管理扩展
  skillImport:   `${API_BASE}/skills/import`,
  skillToggle:   (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}/toggle`,
  skillExport:   (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}/export`,
  skillUpdate:   (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}`,
  skillDelete:   (name: string) => `${API_BASE}/skills/${encodeURIComponent(name)}`,
} as const