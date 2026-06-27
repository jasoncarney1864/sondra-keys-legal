import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  type ImageCandidate,
  canGeneratePdf,
  generatePdfBytes,
  moveImage,
  parseSingleImageFiles,
  parseZipImageFile,
  sanitizePdfName,
} from '../lib/pdf-builder/utils'

export function PdfBuilderPage() {
  const [images, setImages] = useState<ImageCandidate[]>([])
  const [pdfName, setPdfName] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)

  const selectedCount = images.filter((image) => image.selected).length
  const nameValidation = useMemo(() => sanitizePdfName(pdfName), [pdfName])

  async function onSingleImageUpload(fileList: FileList | null) {
    if (!fileList?.length) {
      return
    }

    setError(null)
    const files = Array.from(fileList)
    const parsed = await parseSingleImageFiles(files)

    setImages((current) => [...current, ...parsed.accepted])

    if (parsed.rejected.length) {
      setNotice(`Skipped unsupported files: ${parsed.rejected.join(', ')}`)
    } else {
      setNotice(`Added ${parsed.accepted.length} image${parsed.accepted.length === 1 ? '' : 's'}.`)
    }
  }

  async function onZipUpload(fileList: FileList | null) {
    if (!fileList?.length) {
      return
    }

    setError(null)
    const zipFile = fileList[0]

    if (!zipFile.name.toLowerCase().endsWith('.zip')) {
      setError('Upload a .zip file for batch import.')
      return
    }

    const parsed = await parseZipImageFile(zipFile)
    setImages((current) => [...current, ...parsed.accepted])

    if (parsed.rejected.length) {
      setNotice(`Imported ${parsed.accepted.length} images. Skipped: ${parsed.rejected.join(', ')}`)
    } else {
      setNotice(`Imported ${parsed.accepted.length} images from zip.`)
    }
  }

  function toggleImage(id: string) {
    setImages((current) =>
      current.map((image) =>
        image.id === id
          ? {
              ...image,
              selected: !image.selected,
            }
          : image,
      ),
    )
  }

  function toggleAll(selected: boolean) {
    setImages((current) => current.map((image) => ({ ...image, selected })))
  }

  function removeImage(id: string) {
    setImages((current) => current.filter((image) => image.id !== id))
  }

  function reorder(index: number, direction: 'up' | 'down') {
    setImages((current) => moveImage(current, index, direction))
  }

  async function generatePdf() {
    setError(null)
    setNotice(null)

    if (!nameValidation.isValid) {
      setError(nameValidation.issues[nameValidation.issues.length - 1] ?? 'Enter a valid PDF name.')
      return
    }

    const selectedImages = images.filter((image) => image.selected)
    if (!selectedImages.length) {
      setError('Select at least one image before creating the PDF.')
      return
    }

    try {
      setIsGenerating(true)
      const bytes = await generatePdfBytes(selectedImages)
      const normalizedBytes = Uint8Array.from(bytes)
      const blob = new Blob([normalizedBytes], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)

      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = nameValidation.outputFileName
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)

      setNotice(`Your PDF is ready: ${nameValidation.outputFileName}`)
    } catch (generationError) {
      setError((generationError as Error).message)
    } finally {
      setIsGenerating(false)
    }
  }

  const generationReady = canGeneratePdf({
    selectedCount,
    nameValidation,
    isGenerating,
  })

  return (
    <section>
      <header className="page-header">
        <div>
          <p className="eyebrow">Sondra Keys PDF Builder</p>
          <h2>Build a PDF from your page images</h2>
          <p className="muted">
            Upload images one-by-one or as a zip, pick exactly what to include, then download your PDF.
          </p>
        </div>
        <Link to="/" className="help-card-link pdf-back-link">
          Back to portal
        </Link>
      </header>

      <div className="card">
        <h3>Upload images</h3>
        <div className="pdf-upload-grid">
          <label className="stack-form">
            <span className="label">Upload one at a time</span>
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              multiple
              onChange={(event) => {
                void onSingleImageUpload(event.target.files)
                event.currentTarget.value = ''
              }}
            />
          </label>

          <label className="stack-form">
            <span className="label">Upload as zip</span>
            <input
              type="file"
              accept=".zip"
              onChange={(event) => {
                void onZipUpload(event.target.files)
                event.currentTarget.value = ''
              }}
            />
          </label>
        </div>

        <div className="pdf-actions">
          <button type="button" className="ghost" onClick={() => toggleAll(true)} disabled={!images.length}>
            Select all
          </button>
          <button type="button" className="ghost" onClick={() => toggleAll(false)} disabled={!images.length}>
            Clear all
          </button>
          <p className="muted">Selected: {selectedCount} / {images.length}</p>
        </div>

        {images.length === 0 ? (
          <p className="muted">No images yet. Add files to start your PDF build.</p>
        ) : (
          <div className="pdf-image-grid">
            {images.map((image, index) => (
              <article key={image.id} className="pdf-image-card">
                <img src={image.dataUrl} alt={image.name} className="pdf-image-preview" />
                <label className="inline-checkbox">
                  <input
                    type="checkbox"
                    checked={image.selected}
                    onChange={() => toggleImage(image.id)}
                  />
                  Include this page
                </label>
                <p className="mono">{image.name}</p>
                <div className="row-actions">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => reorder(index, 'up')}
                    disabled={index === 0}
                  >
                    Move up
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => reorder(index, 'down')}
                    disabled={index === images.length - 1}
                  >
                    Move down
                  </button>
                  <button type="button" className="ghost" onClick={() => removeImage(image.id)}>
                    Remove
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3>Name and generate</h3>
        <label className="stack-form" htmlFor="pdf-name">
          <span className="label">PDF name</span>
          <input
            id="pdf-name"
            type="text"
            value={pdfName}
            onChange={(event) => setPdfName(event.target.value)}
            placeholder="Example: Lease Packet March 2026"
            maxLength={130}
          />
        </label>
        <p className="muted">
          Safe output name: <span className="mono">{nameValidation.outputFileName || '(enter a name)'}</span>
        </p>
        {nameValidation.issues.length > 0 ? (
          <ul className="pdf-issues-list">
            {nameValidation.issues.map((issue) => (
              <li key={issue} className="muted">
                {issue}
              </li>
            ))}
          </ul>
        ) : null}

        <button type="button" className="primary" onClick={() => void generatePdf()} disabled={!generationReady}>
          {isGenerating ? 'Generating PDF...' : 'Generate PDF'}
        </button>

        {notice ? <p className="notice success">{notice}</p> : null}
        {error ? <p className="notice error">{error}</p> : null}
      </div>
    </section>
  )
}
