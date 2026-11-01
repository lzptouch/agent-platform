# Agent Skill — PDF 处理 Skill

> **位置说明**：本目录是 `agent skill/` 项目的 4 个 Skill 之一（与 frontend-design、skill-creator、ralph-loop 平级）。
>
> 完整的 `agent skill/` 项目文档以 4 个 Skill 的 README + 全局索引为主。

## Skill 定位

`pdf/` 是 Claude Code 风格的 Skill 文件夹，提供 PDF 处理能力的标准化 prompt。

**核心功能**：
- 提取 PDF 文本（含 OCR 扫描件）
- 合并多个 PDF
- 分割 PDF
- 加密/解密 PDF
- 添加水印
- PDF 转图片

**技术栈**：
- `pypdf`：Python 主流 PDF 库
- `pdfplumber`：表格抽取
- `reportlab`：创建 PDF
- `pdftk`/`qpdf`：命令行 PDF 工具
- `pytesseract` + `pdf2image`：OCR

## 文件清单
- `SKILL.md` — Skill 入口（YAML frontmatter + Markdown 文档）
- `LICENSE.txt` — 许可
- `forms.md` — PDF 表单填写详细指南
- `reference.md` — 高级 API 参考
- `scripts/` — 辅助脚本目录

## 文档清单
- `00-README.md` — 索引（详细）

## 核心原理
1. **pypdf 适合文本型 PDF**；**pdfplumber 适合带表格 PDF**；**OCR 用 pytesseract**。
2. **PDF 操作优先用 pypdf**；CLI 批量用 qpdf / pdftk。
3. **创建 PDF 用 reportlab Canvas** 或 **Platypus 高级文档**。
4. **OCR 必须转图片**（pytesseract 读图不读 PDF）。
5. **加粗体不要用 Unicode 下标**（内置字体不含，需用 `<sub>/<super>` 标签）。

## 引用
- [官方] pypdf 文档
- [官方] pdfplumber 文档
- [官方] reportlab 文档
