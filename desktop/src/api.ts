export type ReceiptItem = {
  id: number
  raw_description: string
  quantity: number
  unit_price_minor: number | null
  discount_minor: number
  line_total_minor: number
}

export type Receipt = {
  id: number
  supermarket_id: number | null
  purchase_date: string | null
  currency: string
  total_minor: number | null
  status: 'pending' | 'processing' | 'needs_review' | 'verified' | 'failed'
  created_at: string
  items: ReceiptItem[]
}

export type OCRRun = {
  id: number
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  confidence: number | null
  engine: string
  engine_version: string | null
  error_message: string | null
  output: {
    text: string
    parsed: { supermarket_name: string | null; warnings: string[] }
  } | null
}

const baseUrl = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    throw new Error(message ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function listReceipts() {
  return request<{ items: Omit<Receipt, 'items'>[] }>('/receipts?limit=20')
}

export function getReceipt(id: number) {
  return request<Receipt>(`/receipts/${id}`)
}

export function getOCR(id: number) {
  return request<OCRRun>(`/receipts/${id}/ocr`)
}

export function uploadReceipt(file: File) {
  const data = new FormData()
  data.append('file', file)
  return request<Omit<Receipt, 'items'>>('/receipts', { method: 'POST', body: data })
}

export function runOCR(id: number) {
  return request<OCRRun>(`/receipts/${id}/ocr`, { method: 'POST' })
}

export function saveReview(id: number, changes: Record<string, unknown>) {
  return request<Receipt>(`/receipts/${id}/review`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(changes),
  })
}

export function verifyReceipt(id: number) {
  return request<Receipt>(`/receipts/${id}/verify`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export async function deleteReceipt(id: number) {
  const response = await fetch(`${baseUrl}/receipts/${id}`, { method: 'DELETE' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed (${response.status})`)
  }
}
