export type ReceiptItem = {
  id: number
  raw_description: string
  quantity: number
  unit_price_pence: number | null
  discount_pence: number
  original_pence: number
  discounts: {
    amount_pence: number
    reason: string | null
    source_text: string
    promotion_group: string | null
  }[]
  promotions: {
    group: string
    marker_text: string
    advertised_quantity: number | null
    advertised_price_pence: number
  }[]
  brand_id: number | null
  brand_name: string | null
  brand_candidate: string | null
  brand_source: 'matched' | 'candidate' | 'supermarket' | null
  category_id: number | null
  category_name: string | null
  category_source: 'matched' | 'suggested' | 'reviewed' | null
}

export type Category = { id: number; name: string }
export type ExpenseCategory = Category

export type MonthlySpending = {
  month: string
  currency: string
  receipt_count: number
  total_pence: number
}

export type CategorySpending = {
  month: string
  currency: string
  category_id: number | null
  category_name: string
  total_pence: number
}

export type ExpenseCategorySpending = {
  month: string
  currency: string
  expense_category_id: number | null
  expense_category_name: string
  receipt_count: number
  total_pence: number
}

export type SupermarketSpending = {
  month: string
  currency: string
  supermarket_id: number
  supermarket_name: string
  receipt_count: number
  total_pence: number
}

export type Receipt = {
  id: number
  supermarket_id: number | null
  supermarket_name: string | null
  expense_category_id: number | null
  expense_category_name: string | null
  purchase_date: string | null
  currency: string
  total_pence: number | null
  voucher_pence: number
  source_path: string | null
  file_sha256: string | null
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
    parsed: {
      supermarket_name: string | null
      date_candidates: string[]
      warnings: string[]
    }
  } | null
}

const baseUrl = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export function receiptDocumentUrl(receiptId: number) {
  return `${baseUrl}/receipts/${receiptId}/document`
}

export function receiptOCRPreviewUrl(receiptId: number, fileHash: string | null) {
  return `${baseUrl}/receipts/${receiptId}/ocr-preview?v=${fileHash ?? ''}`
}

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

export function listCategories() {
  return request<Category[]>('/categories')
}

export function listExpenseCategories() {
  return request<ExpenseCategory[]>('/expense-categories')
}

export function getMonthlySpending() {
  return request<MonthlySpending[]>('/reports/monthly-spending')
}

export function getCategorySpending() {
  return request<CategorySpending[]>('/reports/category-spending')
}

export function getExpenseCategorySpending() {
  return request<ExpenseCategorySpending[]>('/reports/expense-category-spending')
}

export function getSupermarketSpending() {
  return request<SupermarketSpending[]>('/reports/supermarket-spending')
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

export function deleteUnverifiedReceipts() {
  return request<{ deleted: number }>('/receipts/unverified', { method: 'DELETE' })
}
