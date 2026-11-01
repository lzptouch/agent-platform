/**
 * 内置 MCP Server · weather（契约对齐：app/mcp/servers/weather_server.py）。
 *
 * 使用 NWS `api.weather.gov` + 高德（`GAODE_API_KEY`）。
 */
import { settings } from "../../shared/config.js";
import type { BuiltinMcpServer } from "../manager.js";
import type { ToolSchema } from "../../domain/tools/registry.js";

const TOOLS: ToolSchema[] = [
  {
    name: "get_weather",
    description: "按地点查询当前天气与未来预报（NWS / 高德）。",
    input_schema: {
      type: "object",
      properties: {
        location: { type: "string", description: "地点（城市名或经纬度）" },
        latitude: { type: "number", description: "纬度" },
        longitude: { type: "number", description: "经度" },
      },
    },
    source: "mcp",
    mcp_server: "weather",
  },
];

/** 构造 weather Server。 */
export function createWeatherServer(): BuiltinMcpServer {
  return {
    name: "weather",
    tools: TOOLS,
    async call(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
      if (tool !== "get_weather") {
        return { ok: false, error: `未知工具: ${tool}` };
      }
      const location = String(args.location ?? "").trim();
      let lat = args.latitude !== undefined ? Number(args.latitude) : null;
      let lon = args.longitude !== undefined ? Number(args.longitude) : null;

      // 高德地理编码
      if ((lat === null || lon === null) && location && settings.gaode_api_key) {
        try {
          const url = `https://restapi.amap.com/v3/geocode/geo?address=${encodeURIComponent(location)}&key=${settings.gaode_api_key}`;
          const response = await fetch(url);
          const data = (await response.json()) as {
            geocodes?: Array<{ location?: string }>;
          };
          const loc = data.geocodes?.[0]?.location;
          if (loc) {
            const [lng, l] = loc.split(",").map(Number);
            lon = lng;
            lat = l;
          }
        } catch {
          // 地理编码失败 → 落到 NWS
        }
      }

      if (lat === null || lon === null) {
        return {
          ok: false,
          error: "无法解析地点：请提供经纬度，或配置 GAODE_API_KEY 以启用地理编码",
        };
      }

      try {
        const pointsResponse = await fetch(
          `https://api.weather.gov/points/${lat.toFixed(4)},${lon.toFixed(4)}`,
          { headers: { "User-Agent": "agent-desktop", Accept: "application/geo+json" } },
        );
        if (!pointsResponse.ok) {
          return { ok: false, error: `NWS 查询失败: HTTP ${pointsResponse.status}` };
        }
        const points = (await pointsResponse.json()) as {
          properties?: { forecast?: string; gridId?: string; gridX?: number; gridY?: number };
        };
        const forecastUrl = points.properties?.forecast;
        if (!forecastUrl) {
          return { ok: false, error: "NWS 未返回预报地址" };
        }
        const forecastResponse = await fetch(forecastUrl, {
          headers: { "User-Agent": "agent-desktop", Accept: "application/geo+json" },
        });
        const forecast = (await forecastResponse.json()) as {
          properties?: {
            periods?: Array<{
              name?: string;
              temperature?: number;
              temperatureUnit?: string;
              windSpeed?: string;
              shortForecast?: string;
            }>;
          };
        };
        const periods = (forecast.properties?.periods ?? []).slice(0, 5).map((p) => ({
          name: p.name ?? "",
          temperature: p.temperature ?? null,
          temperature_unit: p.temperatureUnit ?? "",
          wind_speed: p.windSpeed ?? "",
          forecast: p.shortForecast ?? "",
        }));
        return { ok: true, latitude: lat, longitude: lon, periods };
      } catch (err) {
        return { ok: false, error: `天气查询失败: ${(err as Error).message}` };
      }
    },
  };
}
