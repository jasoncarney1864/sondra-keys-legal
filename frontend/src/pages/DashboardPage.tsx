import { Link } from 'react-router-dom'

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
            <p>Keep conversation continuity by session and clean up old sessions when needed.</p>
          </article>
        </div>

        <article className="dashboard-start">
          <h3>Getting Started</h3>
          <div className="dashboard-howto-grid">
            <section className="dashboard-howto-step">
              <h4>Step 1: Create Session</h4>
              <ol className="dashboard-start-list">
                <li>Click Sessions in the left menu.</li>
                <li>Click Create session at the top-right.</li>
                <li>In the popup, choose a file if you want to upload now.</li>
                <li>Click Create now or Create + upload.</li>
              </ol>
              <Link className="dashboard-step-link" to="/legal/sessions">
                Open Sessions
              </Link>
            </section>

            <section className="dashboard-howto-step">
              <h4>Step 2: Upload Documents</h4>
              <ol className="dashboard-start-list">
                <li>Click Documents in the left menu.</li>
                <li>Upload a file if one is not already listed.</li>
                <li>Wait for processing to show Completed.</li>
                <li>Use these files later in Ask explicit document scope.</li>
              </ol>
              <Link className="dashboard-step-link" to="/legal/documents">
                Open Documents
              </Link>
            </section>

            <section className="dashboard-howto-step">
              <h4>Step 3: Ask a Question</h4>
              <ol className="dashboard-start-list">
                <li>Click Ask in the left menu.</li>
                <li>Enter a plain-language question in Prompt.</li>
                <li>Check one or more documents in explicit document scope.</li>
                <li>Click Ask question and review Answer + Citations.</li>
              </ol>
              <Link className="dashboard-step-link" to="/legal/ask">
                Open Ask
              </Link>
            </section>
          </div>
        </article>
      </div>
    </section>
  )
}
