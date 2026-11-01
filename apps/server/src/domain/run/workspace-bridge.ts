/**
 * 工作空间服务桥接。
 *
 * `run` 需要在创建时绑定工作空间；`workspace` **不依赖** `run`，因此这里不存在
 * 真正的循环依赖——保留本文件是为了把「运行期绑定工作空间」这一语义集中一处，
 * 并在测试中可替换实现。
 */
import { workspaceService, type WorkspaceService } from "../workspace/service.js";

let injected: WorkspaceService | null = null;

/** 取得工作空间服务（测试可注入替身）。 */
export function workspaceModule(): { workspaceService: WorkspaceService } {
  return { workspaceService: injected ?? workspaceService };
}

/** 注入实现（测试用）。 */
export function setWorkspaceService(svc: WorkspaceService): void {
  injected = svc;
}
