import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'

import {
  canGeneratePdf,
  classifySingleImageUpload,
  generatePdfBytes,
  moveImage,
  parseZipImageBytes,
  sanitizePdfName,
  type ImageCandidate,
} from './utils'

const TINY_PNG_DATA_URL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAgMBgNktn5kAAAAASUVORK5CYII='

function createCandidate(name: string): ImageCandidate {
  return {
    id: name,
    name,
    mimeType: 'image/png',
    dataUrl: TINY_PNG_DATA_URL,
    selected: true,
  }
}

describe('sanitizePdfName', () => {
  it('replaces invalid characters and trims spacing', () => {
    const result = sanitizePdfName('  Lease:Packet*2026  ')
    expect(result.isValid).toBe(true)
    expect(result.outputFileName).toBe('Lease-Packet-2026.pdf')
    expect(result.issues.length).toBeGreaterThan(0)
  })

  it('handles reserved names safely', () => {
    const result = sanitizePdfName('CON')
    expect(result.isValid).toBe(true)
    expect(result.sanitizedBaseName).toBe('CON-file')
  })

  it('fails when no usable name is left', () => {
    const result = sanitizePdfName('   ')
    expect(result.isValid).toBe(false)
    expect(result.outputFileName).toBe('')
  })
})

describe('single image upload classification', () => {
  it('accepts supported image extensions and rejects others', () => {
    const result = classifySingleImageUpload([
      { name: 'page-1.png' },
      { name: 'page-2.jpg' },
      { name: 'notes.txt' },
    ])

    expect(result.acceptedFileNames).toEqual(['page-1.png', 'page-2.jpg'])
    expect(result.rejected).toEqual(['notes.txt (unsupported type)'])
  })
})

describe('zip image parsing', () => {
  it('extracts supported images and reports unsupported files', async () => {
    const zip = new JSZip()
    zip.file('p1.png', Buffer.from([137, 80, 78, 71]))
    zip.file('p2.webp', Buffer.from([82, 73, 70, 70]))
    zip.file('readme.md', 'skip me')

    const bytes = await zip.generateAsync({ type: 'arraybuffer' })
    const result = await parseZipImageBytes(bytes)

    expect(result.accepted.map((item) => item.name)).toEqual(['p1.png', 'p2.webp'])
    expect(result.rejected).toEqual(['readme.md (unsupported type)'])
  })
})

describe('image selection/order helpers', () => {
  it('moves an image down and preserves other items', () => {
    const start = [createCandidate('a'), createCandidate('b'), createCandidate('c')]
    const moved = moveImage(start, 0, 'down')

    expect(moved.map((item) => item.id)).toEqual(['b', 'a', 'c'])
  })
})

describe('generate button rules', () => {
  it('enables only when name is valid, at least one selected, and not generating', () => {
    const validName = sanitizePdfName('Packet 2026')

    expect(
      canGeneratePdf({
        selectedCount: 1,
        nameValidation: validName,
        isGenerating: false,
      }),
    ).toBe(true)

    expect(
      canGeneratePdf({
        selectedCount: 0,
        nameValidation: validName,
        isGenerating: false,
      }),
    ).toBe(false)
  })
})

describe('PDF generation', () => {
  it('creates a PDF byte array from selected images', async () => {
    const bytes = await generatePdfBytes([createCandidate('page-1')])
    const prefix = new TextDecoder().decode(bytes.slice(0, 4))

    expect(prefix).toBe('%PDF')
    expect(bytes.length).toBeGreaterThan(100)
  })
})
