// Single entry point the UI talks to. Step 2+ adds an HTTP client for the FastAPI backend
// with the same method names and switches on NEXT_PUBLIC_API_MODE.
export { mockApi as api, ApiError } from "./mock-api";
export { useWorkspace, useWorkspaceOrNull } from "./store";
