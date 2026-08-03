export default function ComingSoonPage({ title }) {
  return (
    <div>
      <header className="page-header">
        <div>
          <p className="eyebrow">MODULE</p>
          <h1>{title}</h1>
          <p className="muted">다음 버전에서 이 모듈을 연결합니다.</p>
        </div>
      </header>
      <section className="panel coming-soon">
        <div className="coming-icon">JM</div>
        <h2>{title} 준비 중</h2>
        <p className="muted">메뉴 구조는 먼저 만들어두었고 기능을 순차적으로 추가합니다.</p>
      </section>
    </div>
  );
}
