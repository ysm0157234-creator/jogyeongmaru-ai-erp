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
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response;

  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  } catch (err) {
    console.error("API Fetch Error:", err);
    throw new Error("서버에 연결할 수 없습니다.\n\n" + err.message);
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
    } catch (e) {
      console.error(e);
    }

    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function apiDownload(path, options = {}) {
  const headers = new Headers(options.headers || {});

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response;

  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  } catch (err) {
    console.error("DOWNLOAD FETCH ERROR:", err);
    throw new Error("Fetch 실패 : " + err.message);
  }

  if (response.status === 401) {
    clearToken();
    window.location.href = "/login";
  }

  if (!response.ok) {
    let message = "파일 생성 실패";

    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (e) {
      console.error(e);
    }

    throw new Error(message);
  }

  return response;
}

export { API_URL };
