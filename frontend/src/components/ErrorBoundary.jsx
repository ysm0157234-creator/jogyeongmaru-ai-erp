import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || "알 수 없는 화면 오류가 발생했습니다.",
    };
  }

  componentDidCatch(error, info) {
    console.error("Frontend error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
          background: "#f7f8fa",
          fontFamily: 'Inter, "Apple SD Gothic Neo", sans-serif'
        }}>
          <div style={{
            maxWidth: 560,
            width: "100%",
            background: "white",
            border: "1px solid #e5e8eb",
            borderRadius: 20,
            padding: 28
          }}>
            <h1 style={{ marginTop: 0 }}>화면을 불러오지 못했습니다.</h1>
            <p style={{ color: "#6b7684", lineHeight: 1.6 }}>
              새로고침 후에도 같은 문제가 생기면 아래 오류 내용을 캡처해 주세요.
            </p>
            <pre style={{
              whiteSpace: "pre-wrap",
              background: "#f2f4f6",
              borderRadius: 12,
              padding: 14,
              overflow: "auto"
            }}>{this.state.message}</pre>
            <button
              onClick={() => window.location.reload()}
              style={{
                border: 0,
                borderRadius: 12,
                padding: "12px 16px",
                background: "#3182f6",
                color: "white",
                fontWeight: 800,
                cursor: "pointer"
              }}
            >
              새로고침
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
