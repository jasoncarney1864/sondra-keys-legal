type DashboardPageProps = {
  authIdentity: string | null
}

export function DashboardPage({ authIdentity }: DashboardPageProps) {
  const greetingName = authIdentity ?? 'there'

  return (
    <section className="dashboard-page">
      <div className="dashboard-art-layer" aria-hidden="true">
        <img src="/art/sunflowers-oil.svg" alt="" className="dashboard-art sunflower" />
      </div>

      <div className="dashboard-card">
        <p className="eyebrow">Welcome</p>
        <h2>Good to see you, {greetingName}.</h2>
        <p className="dashboard-lead">
          This workspace helps you upload legal documents, run grounded question-answering,
          manage sticky sessions, and keep answers tied to traceable citations.
        </p>

        <div className="dashboard-grid">
          <article className="dashboard-tile">
            <h3>Documents</h3>
            <p>Upload PDF, DOCX, DOC, or TXT files and monitor extraction/indexing progress.</p>
          </article>
          <article className="dashboard-tile">
            <h3>Ask</h3>
            <p>Ask plain-language questions and receive answers backed by citation snippets.</p>
          </article>
          <article className="dashboard-tile">
            <h3>Sessions</h3>
            <p>Keep work scoped by session, set active documents, and clean up old sessions.</p>
          </article>
        </div>
      </div>
    </section>
  )
}
