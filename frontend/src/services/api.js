const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export function getToken() {
  return localStorage.getItem("jm_token");
}

export function setToken(token) {
  localStorage.setItem("jm_token", token);
}

export function clearToken() {
  localStorage.removeItem("jm_token");
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const hasBody = options.body !== undefined && options.body !== null;

  if (hasBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  } catch {
    throw new Error("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.");
  }

  if (response.status === 401) {
    clearToken();
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  if (!response.ok) {
    let message = "요청 처리 중 오류가 발생했습니다.";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }

  if (response.status === 204) return null;
  return response.json();
}

export { API_URL };


export async function apiDownload(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = "파일 생성 중 오류가 발생했습니다.";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return response;
}

export async function apiUpload(path, formData) {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!response.ok) {
    let message = "파일 업로드 중 오류가 발생했습니다.";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return response.json();
}
