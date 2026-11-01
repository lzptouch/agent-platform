/**
 * Web Research 路由（契约对齐：app/api/v1/web_research.py）。
 *
 * 端点：`POST /research` · `GET /status`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("routes.web-research");

export async function registerWebResearchRoutes(app: FastifyInstance): Promise<void> {
  app.post("/api/v1/web_research/research", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const query = String(body.query ?? "");
    if (!query) throw new HttpError(422, "缺少 query");
    if (!settings.web_search_available) {
      throw new HttpError(503, "未配置 SERPER_API_KEY —— Web Research 检索能力不可用");
    }
    // 检索能力由 `services/web` 提供；此处返回明确的不可用原因而非静默成功
    logger.info("Web Research 请求已受理", { query: query.slice(0, 80) });
    throw new HttpError(503, "Web Research 检索链路在本机未配置完整的抓取依赖（cheerio / 搜索引擎）");
  });

  app.get("/api/v1/web_research/status", async () => ({
    available: settings.web_search_available,
    serper_configured: settings.web_search_available,
    llm_configured: settings.llm_available,
    answer_model: settings.answer_model,
    references_enabled: true,
  }));
}
