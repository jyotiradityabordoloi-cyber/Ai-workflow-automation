// Single entry point the UI talks to.
//   NEXT_PUBLIC_API_MODE=live  -> FastAPI backend for tickets + classification (step 2)
//   otherwise                  -> in-browser mock (step 1)
import { liveApi } from "./live-api";
import { mockApi } from "./mock-api";

export const api = process.env.NEXT_PUBLIC_API_MODE === "live" ? liveApi : mockApi;
export { ApiError } from "./mock-api";
export { API_URL } from "./live-api";
export { useWorkspace, useWorkspaceOrNull } from "./store";
