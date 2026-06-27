import JSZip from 'jszip'
import { PDFDocument } from 'pdf-lib'

export const MAX_PDF_NAME_LENGTH = 100
const INVALID_NAME_CHARS = /[\\/:*?"<>|]/g
const REPEATED_SPACES = /\s+/g
const TRAILING_DOTS_SPACES = /[.\s]+$/g
const RESERVED_NAMES = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i

const SUPPORTED_MIME_BY_EXT: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
}

export type ImageCandidate = {
  id: string
  name: string
  mimeType: string
  dataUrl: string
  selected: boolean
}

export type PdfNameValidation = {
  raw: string
  sanitizedBaseName: string
  outputFileName: string
  issues: string[]
  isValid: boolean
}

function getExt(fileName: string): string {
  const ext = fileName.split('.').pop() ?? ''
  return ext.toLowerCase()
}

export function isSupportedImageName(fileName: string): boolean {
  return Object.prototype.hasOwnProperty.call(SUPPORTED_MIME_BY_EXT, getExt(fileName))
}

export function classifySingleImageUpload(files: Array<{ name: string }>): {
  acceptedFileNames: string[]
  rejected: string[]
} {
  const acceptedFileNames: string[] = []
  const rejected: string[] = []

  for (const file of files) {
    if (isSupportedImageName(file.name)) {
      acceptedFileNames.push(file.name)
    } else {
      rejected.push(`${file.name} (unsupported type)`)
    }
  }

  return {
    acceptedFileNames,
    rejected,
  }
}

export function sanitizePdfName(rawInput: string): PdfNameValidation {
  const issues: string[] = []
  const raw = rawInput ?? ''
  let next = raw.trim().replace(REPEATED_SPACES, ' ')

  if (next !== raw) {
    issues.push('Extra spacing was cleaned up.')
  }

  if (/\.pdf$/i.test(next)) {
    next = next.replace(/\.pdf$/i, '')
    issues.push('Removed .pdf extension; it is added automatically.')
  }

  const replacedChars = next.match(INVALID_NAME_CHARS)
  if (replacedChars?.length) {
    next = next.replace(INVALID_NAME_CHARS, '-')
    issues.push('Invalid filename characters were replaced with dashes.')
  }

  next = next.replace(TRAILING_DOTS_SPACES, '')

  if (RESERVED_NAMES.test(next)) {
    next = `${next}-file`
    issues.push('Reserved filename adjusted to a safe value.')
  }

  if (next.length > MAX_PDF_NAME_LENGTH) {
    next = next.slice(0, MAX_PDF_NAME_LENGTH).replace(TRAILING_DOTS_SPACES, '')
    issues.push(`Name was trimmed to ${MAX_PDF_NAME_LENGTH} characters.`)
  }

  if (!next) {
    issues.push('Enter a PDF name.')
    return {
      raw,
      sanitizedBaseName: '',
      outputFileName: '',
      issues,
      isValid: false,
    }
  }

  return {
    raw,
    sanitizedBaseName: next,
    outputFileName: `${next}.pdf`,
    issues,
    isValid: true,
  }
}

export function canGeneratePdf(args: {
  selectedCount: number
  nameValidation: PdfNameValidation
  isGenerating: boolean
}): boolean {
  return args.selectedCount > 0 && args.nameValidation.isValid && !args.isGenerating
}

function generateId(seed: string, index: number): string {
  return `${seed}-${index}-${Math.random().toString(36).slice(2, 9)}`
}

export async function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error(`Failed to read ${file.name}.`))
        return
      }
      resolve(reader.result)
    }
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}.`))
    reader.readAsDataURL(file)
  })
}

export async function parseSingleImageFiles(files: File[]): Promise<{ accepted: ImageCandidate[]; rejected: string[] }> {
  const accepted: ImageCandidate[] = []
  const { acceptedFileNames, rejected } = classifySingleImageUpload(files)

  for (let i = 0; i < files.length; i += 1) {
    const file = files[i]
    if (!acceptedFileNames.includes(file.name)) {
      continue
    }

    const ext = getExt(file.name)
    const mimeType = file.type || SUPPORTED_MIME_BY_EXT[ext]
    const dataUrl = await readFileAsDataUrl(file)

    accepted.push({
      id: generateId(file.name, i),
      name: file.name,
      mimeType,
      dataUrl,
      selected: true,
    })
  }

  return { accepted, rejected }
}

export async function parseZipImageBytes(zipBytes: ArrayBuffer): Promise<{ accepted: ImageCandidate[]; rejected: string[] }> {
  const accepted: ImageCandidate[] = []
  const rejected: string[] = []
  const zip = await JSZip.loadAsync(zipBytes)
  const fileNames = Object.keys(zip.files).sort((a, b) => a.localeCompare(b))

  for (let i = 0; i < fileNames.length; i += 1) {
    const name = fileNames[i]
    const entry = zip.files[name]

    if (entry.dir) {
      continue
    }

    if (!isSupportedImageName(entry.name)) {
      rejected.push(`${entry.name} (unsupported type)`)
      continue
    }

    const ext = getExt(entry.name)
    const mimeType = SUPPORTED_MIME_BY_EXT[ext]
    const base64 = await entry.async('base64')

    accepted.push({
      id: generateId(entry.name, i),
      name: entry.name,
      mimeType,
      dataUrl: `data:${mimeType};base64,${base64}`,
      selected: true,
    })
  }

  return { accepted, rejected }
}

export async function parseZipImageFile(zipFile: File): Promise<{ accepted: ImageCandidate[]; rejected: string[] }> {
  const zipBytes = await zipFile.arrayBuffer()
  return parseZipImageBytes(zipBytes)
}

function dataUrlToBytes(dataUrl: string): Uint8Array {
  const commaIndex = dataUrl.indexOf(',')
  const base64 = commaIndex >= 0 ? dataUrl.slice(commaIndex + 1) : dataUrl
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

async function convertWebpDataUrlToPngDataUrl(webpDataUrl: string): Promise<string> {
  if (typeof document === 'undefined') {
    throw new Error('WebP conversion requires browser APIs.')
  }

  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext('2d')
      if (!context) {
        reject(new Error('Unable to prepare canvas conversion for WebP image.'))
        return
      }
      context.drawImage(image, 0, 0)
      resolve(canvas.toDataURL('image/png'))
    }
    image.onerror = () => reject(new Error('Unable to decode WebP image for PDF output.'))
    image.src = webpDataUrl
  })
}

async function embedCandidate(pdfDoc: PDFDocument, image: ImageCandidate) {
  if (image.mimeType === 'image/png') {
    const embedded = await pdfDoc.embedPng(dataUrlToBytes(image.dataUrl))
    return { embedded, width: embedded.width, height: embedded.height }
  }

  if (image.mimeType === 'image/jpeg') {
    const embedded = await pdfDoc.embedJpg(dataUrlToBytes(image.dataUrl))
    return { embedded, width: embedded.width, height: embedded.height }
  }

  if (image.mimeType === 'image/webp') {
    const pngDataUrl = await convertWebpDataUrlToPngDataUrl(image.dataUrl)
    const embedded = await pdfDoc.embedPng(dataUrlToBytes(pngDataUrl))
    return { embedded, width: embedded.width, height: embedded.height }
  }

  throw new Error(`Unsupported image format for PDF: ${image.name}`)
}

export async function generatePdfBytes(images: ImageCandidate[]): Promise<Uint8Array> {
  if (!images.length) {
    throw new Error('Select at least one image to create a PDF.')
  }

  const pdfDoc = await PDFDocument.create()

  for (const image of images) {
    const { embedded, width, height } = await embedCandidate(pdfDoc, image)
    const page = pdfDoc.addPage([width, height])
    page.drawImage(embedded, {
      x: 0,
      y: 0,
      width,
      height,
    })
  }

  return pdfDoc.save()
}

export function moveImage(images: ImageCandidate[], index: number, direction: 'up' | 'down'): ImageCandidate[] {
  if (direction === 'up' && index === 0) {
    return images
  }

  if (direction === 'down' && index === images.length - 1) {
    return images
  }

  const next = [...images]
  const target = direction === 'up' ? index - 1 : index + 1
  const temp = next[target]
  next[target] = next[index]
  next[index] = temp
  return next
}
