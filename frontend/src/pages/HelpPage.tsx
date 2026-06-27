import { Link } from 'react-router-dom'

type HelpTopic = {
  title: string
  description: string
  linkLabel: string
  to: string
}

const topics: HelpTopic[] = [
  {
    title: 'Dashboard overview',
    description:
      'Quick snapshot of what the app does and the recommended first steps.',
    linkLabel: 'Open Dashboard details',
    to: '/legal/dashboard',
  },
  {
    title: 'Session setup and context',
    description:
      'How to create a session, upload during setup, and keep work scoped to the right context.',
    linkLabel: 'Open Sessions details',
    to: '/legal/sessions',
  },
  {
    title: 'Document upload and readiness',
    description:
      'How to upload files, monitor processing, and prepare documents for explicit question scope.',
    linkLabel: 'Open Documents details',
    to: '/legal/documents',
  },
  {
    title: 'Asking questions with citations',
    description:
      'How to ask in plain language and select explicit document scope for each question.',
    linkLabel: 'Open Ask details',
    to: '/legal/ask',
  },
  {
    title: 'Explicit scope quick actions',
    description:
      'Use checkboxes, select all, and clear all to scope each question quickly and clearly.',
    linkLabel: 'Open Ask scope options',
    to: '/legal/ask',
  },
  {
    title: 'PDF Builder from image pages',
    description:
      'Upload page images as a zip or one-by-one, choose what to include, and generate a clean PDF download.',
    linkLabel: 'Open PDF Builder details',
    to: '/pdf-builder',
  },
]

export function HelpPage() {
  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Help</p>
          <h2>Help Center</h2>
          <p className="muted">
            Relaxed, quick guides to what Sondra Keys Legal does and where to go for the full flow.
          </p>
        </div>
      </header>

      <div className="help-grid">
        {topics.map((topic) => (
          <article key={topic.title} className="help-card">
            <h3>{topic.title}</h3>
            <p>{topic.description}</p>
            <Link to={topic.to} className="help-card-link">
              {topic.linkLabel}
            </Link>
          </article>
        ))}
      </div>

      <article className="help-support card">
        <h3>Need more help?</h3>
        <p className="muted">
          No worries. Here are the quick fixes people usually need first.
        </p>
        <ul className="help-support-list">
          <li>
            <span>Can not ask yet?</span>
            <Link to="/legal/sessions" className="help-card-link">
              Create or switch session
            </Link>
          </li>
          <li>
            <span>Getting no answer or missing citations?</span>
            <Link to="/legal/documents" className="help-card-link">
              Check document status
            </Link>
          </li>
          <li>
            <span>Need tighter control over which docs are used?</span>
            <Link to="/legal/ask" className="help-card-link">
              Use explicit document scope
            </Link>
          </li>
          <li>
            <span>Need a PDF from image pages?</span>
            <Link to="/pdf-builder" className="help-card-link">
              Open PDF Builder
            </Link>
          </li>
        </ul>
      </article>
    </section>
  )
}
