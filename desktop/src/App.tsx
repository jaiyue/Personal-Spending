import { FormEvent, KeyboardEvent, useEffect, useState } from 'react'
import {
  deleteReceipt,
  deleteUnverifiedReceipts,
  getOCR,
  getCategorySpending,
  getExpenseCategorySpending,
  getMonthlySpending,
  getSupermarketSpending,
  getReceipt,
  listCategories,
  listExpenseCategories,
  listReceipts,
  receiptDocumentUrl,
  receiptOCRPreviewUrl,
  runOCR,
  saveReview,
  uploadReceipt,
  verifyReceipt,
  type OCRRun,
  type Receipt,
  type Category,
  type ExpenseCategory,
  type CategorySpending,
  type ExpenseCategorySpending,
  type MonthlySpending,
  type SupermarketSpending,
} from './api'

function money(value: number | null, currency = 'GBP') {
  if (value === null) return '—'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(value / 100)
}

function displayDate(value: string | null) {
  if (!value) return ''
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value
}

function storageDate(value: string) {
  if (!value) return null
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value)
  return match ? `${match[3]}-${match[2]}-${match[1]}` : value
}

function ItemCell({ value, label, editable }: { value: string | number; label: string; editable: boolean }) {
  const original = String(value)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(original)
  const [edited, setEdited] = useState<string | null>(null)
  const changed = edited !== null && edited !== original

  function startEditing() {
    setDraft(edited ?? original)
    setEditing(true)
  }

  function finishEditing() {
    setEdited(draft)
    setEditing(false)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') event.currentTarget.blur()
    if (event.key === 'Escape') {
      setDraft(edited ?? original)
      setEditing(false)
    }
  }

  if (!editable) return <td>{original}</td>

  return <td><div
    className="item-cell-content"
    role="button"
    tabIndex={0}
    aria-label={`Edit ${label}`}
    onClick={startEditing}
    onKeyDown={(event) => {
      if (!editing && (event.key === 'Enter' || event.key === ' ')) startEditing()
    }}
  >
    <span className="original-cell-value">{original}</span>
    {changed && <span className="edited-cell-value">{edited || '(empty)'}</span>}
    {editing && <input
      autoFocus
      type="text"
      value={draft}
      aria-label={`${label} input`}
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={finishEditing}
      onKeyDown={handleKeyDown}
    />}
  </div></td>
}

function BrandCell({ item, editable, onChange }: {
  item: Receipt['items'][number]
  editable: boolean
  onChange: (value: string) => void
}) {
  if (item.brand_id !== null || !editable) return <td><span className="matched-brand">{item.brand_name ?? '—'}</span></td>
  return <td><input
    className="brand-input"
    type="text"
    value={item.brand_name ?? ''}
    aria-label={`Brand for ${item.raw_description}`}
    title={item.brand_source === 'candidate' ? 'Possible brand detected from the item name' : 'Using the supermarket as the default brand'}
    onChange={(event) => onChange(event.target.value)}
  /></td>
}

function CategoryCell({ item, categories, editable, onChange }: {
  item: Receipt['items'][number]
  categories: Category[]
  editable: boolean
  onChange: (categoryId: number | null) => void
}) {
  if (!editable) return <td>{item.category_name ?? 'Uncategorised'}</td>
  return <td><select
    className="category-select"
    value={item.category_id ?? ''}
    aria-label={`Category for ${item.raw_description}`}
    onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
  >
    <option value="">Uncategorised</option>
    {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
  </select></td>
}

function AnalysisPage({ onBack }: { onBack: () => void }) {
  const [monthly, setMonthly] = useState<MonthlySpending[]>([])
  const [categories, setCategories] = useState<CategorySpending[]>([])
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategorySpending[]>([])
  const [supermarkets, setSupermarkets] = useState<SupermarketSpending[]>([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    Promise.all([getMonthlySpending(), getCategorySpending(), getExpenseCategorySpending(), getSupermarketSpending()])
      .then(([nextMonthly, nextCategories, nextExpenseCategories, nextSupermarkets]) => {
        setMonthly(nextMonthly)
        setCategories(nextCategories)
        setExpenseCategories(nextExpenseCategories)
        setSupermarkets(nextSupermarkets)
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : 'Could not load analysis.')
      })
  }, [])

  return <main>
    <header>
      <div>
        <p className="eyebrow">Personal spending</p>
        <div className="page-heading"><h1>Analyse</h1><button className="navigation-link" onClick={onBack}>← Upload and review</button></div>
      </div>
      <p className="subtle">Verified receipts only</p>
    </header>

    {message && <p className="message" role="status">{message}</p>}
    {!message && monthly.length === 0 ? <p className="empty">No verified receipts to analyse yet.</p> : <>
      <section className="analysis-summary">
        {monthly.map((row) => <div className="panel" key={`${row.month}-${row.currency}`}>
          <span>{row.month} · {row.receipt_count} receipt{row.receipt_count === 1 ? '' : 's'}</span>
          <strong>{money(row.total_pence, row.currency)}</strong>
        </div>)}
      </section>

      <section className="analysis-grid">
        <section className="panel"><h2>By expense category</h2>
          <table className="analysis-table"><thead><tr><th>Category</th><th>Receipts</th><th>Total</th></tr></thead>
            <tbody>{expenseCategories.map((row) => <tr key={`${row.month}-${row.currency}-${row.expense_category_id ?? 'none'}`}>
              <td>{row.expense_category_name}</td><td>{row.receipt_count}</td><td>{money(row.total_pence, row.currency)}</td>
            </tr>)}</tbody>
          </table>
        </section>
        <section className="panel"><h2>By category</h2>
          <table className="analysis-table"><thead><tr><th>Category</th><th>Month</th><th>Total</th></tr></thead>
            <tbody>{categories.map((row) => <tr key={`${row.month}-${row.currency}-${row.category_id ?? 'none'}`}>
              <td>{row.category_name}</td><td>{row.month}</td><td>{money(row.total_pence, row.currency)}</td>
            </tr>)}</tbody>
          </table>
        </section>
        <section className="panel"><h2>By supermarket</h2>
          <table className="analysis-table"><thead><tr><th>Supermarket</th><th>Receipts</th><th>Total</th></tr></thead>
            <tbody>{supermarkets.map((row) => <tr key={`${row.month}-${row.currency}-${row.supermarket_id}`}>
              <td>{row.supermarket_name}</td><td>{row.receipt_count}</td><td>{money(row.total_pence, row.currency)}</td>
            </tr>)}</tbody>
          </table>
        </section>
      </section>
    </>}
  </main>
}

function App() {
  const [page, setPage] = useState<'review' | 'analysis'>('review')
  const [receipts, setReceipts] = useState<Omit<Receipt, 'items'>[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([])
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [receiptMode, setReceiptMode] = useState<'compare' | 'details'>('compare')
  const [ocr, setOcr] = useState<OCRRun | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [store, setStore] = useState('')
  const [date, setDate] = useState('')
  const [total, setTotal] = useState('')
  const [voucher, setVoucher] = useState('')
  const [expenseCategoryId, setExpenseCategoryId] = useState('')
  const itemsOriginalTotal = receipt?.items.reduce((sum, item) => sum + item.original_pence, 0) ?? 0
  const itemsDiscountTotal = receipt?.items.reduce((sum, item) => sum + item.discount_pence, 0) ?? 0
  const receiptGroups = receipts.reduce<Record<string, typeof receipts>>((groups, item) => {
    const key = item.purchase_date ?? 'No date'
    ;(groups[key] ??= []).push(item)
    return groups
  }, {})

  function reviewedItems(current: Receipt) {
    return current.items.map(({ raw_description, quantity, unit_price_pence, discount_pence, original_pence,
      brand_name, brand_candidate, brand_source, category_id, discounts, promotions }) => ({
      raw_description, quantity, unit_price_pence, discount_pence, original_pence,
      brand_name, brand_candidate, brand_source, category_id, discounts, promotions,
    }))
  }

  function updateItemBrand(index: number, brandName: string) {
    setReceipt((current) => current ? {
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index
        ? { ...item, brand_name: brandName }
        : item),
    } : current)
  }

  function updateItemCategory(index: number, categoryId: number | null) {
    setReceipt((current) => current ? {
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index
        ? { ...item, category_id: categoryId, category_name: categories.find((category) => category.id === categoryId)?.name ?? null,
          category_source: 'reviewed' }
        : item),
    } : current)
  }

  async function load(id: number) {
    setBusy(true)
    try {
      const [nextReceipt, nextOcr] = await Promise.all([
        getReceipt(id),
        getOCR(id).catch(() => null),
      ])
      setReceipt(nextReceipt)
      setOcr(nextOcr)
      setMessage('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load this receipt.')
    } finally {
      setBusy(false)
    }
  }

  async function refreshList() {
    try {
      const page = await listReceipts()
      setReceipts(page.items)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load receipts.')
    }
  }

  useEffect(() => {
    void refreshList()
    void listCategories().then(setCategories).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : 'Could not load categories.')
    })
    void listExpenseCategories().then(setExpenseCategories).catch((error: unknown) => {
      setMessage(error instanceof Error ? error.message : 'Could not load expense categories.')
    })
  }, [])

  useEffect(() => {
    if (!receipt) return
    setStore(ocr?.output?.parsed.supermarket_name ?? '')
    setDate(displayDate(receipt.purchase_date))
    setTotal(receipt.total_pence === null ? '' : (receipt.total_pence / 100).toFixed(2))
    setVoucher((receipt.voucher_pence / 100).toFixed(2))
    setExpenseCategoryId(receipt.expense_category_id?.toString() ?? '')
  }, [receipt, ocr])

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (files.length === 0) {
      setMessage('Choose one or more JPG, PNG, or PDF receipts first.')
      return
    }
    setBusy(true)
    setMessage(`Uploading and reading ${files.length} receipt${files.length === 1 ? '' : 's'}…`)
    try {
      let lastReceiptId: number | null = null
      const failures: string[] = []
      for (const file of files) {
        try {
          const created = await uploadReceipt(file)
          await runOCR(created.id)
          lastReceiptId = created.id
        } catch (error) {
          failures.push(`${file.name}: ${error instanceof Error ? error.message : 'Upload failed.'}`)
        }
      }
      await refreshList()
      if (lastReceiptId !== null) await load(lastReceiptId)
      setFiles([])
      setMessage(failures.length
        ? `${files.length - failures.length} receipt${files.length - failures.length === 1 ? '' : 's'} analysed. ${failures.join(' ')}`
        : `${files.length} receipt${files.length === 1 ? '' : 's'} saved and analysed.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not refresh uploaded receipts.')
    } finally {
      setBusy(false)
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!receipt) return
    setBusy(true)
    try {
      const updated = await saveReview(receipt.id, {
        supermarket_name: store || null,
        expense_category_id: expenseCategoryId ? Number(expenseCategoryId) : null,
        purchase_date: storageDate(date),
        total_pence: total ? Math.round(Number(total) * 100) : null,
        voucher_pence: voucher ? Math.round(Number(voucher) * 100) : 0,
        items: reviewedItems(receipt),
      })
      setReceipt(updated)
      await refreshList()
      setMessage('Review changes saved.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save changes.')
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!receipt) return
    setBusy(true)
    try {
      await saveReview(receipt.id, {
        supermarket_name: store || null,
        expense_category_id: expenseCategoryId ? Number(expenseCategoryId) : null,
        purchase_date: storageDate(date),
        total_pence: total ? Math.round(Number(total) * 100) : null,
        voucher_pence: voucher ? Math.round(Number(voucher) * 100) : 0,
        items: reviewedItems(receipt),
      })
      setReceipt(await verifyReceipt(receipt.id))
      await refreshList()
      setMessage('Receipt verified.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not verify this receipt.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!receipt || !window.confirm(`Delete receipt #${receipt.id}? This also removes its file and OCR data.`)) return
    setBusy(true)
    try {
      await deleteReceipt(receipt.id)
      setReceipt(null)
      setOcr(null)
      await refreshList()
      setMessage('Receipt deleted.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not delete this receipt.')
    } finally {
      setBusy(false)
    }
  }

  async function removeUnverified() {
    const count = receipts.filter((item) => item.status !== 'verified').length
    if (count === 0 || !window.confirm(`Delete ${count} unverified receipt${count === 1 ? '' : 's'}? This also removes their files and OCR data.`)) return
    setBusy(true)
    try {
      const result = await deleteUnverifiedReceipts()
      if (receipt?.status !== 'verified') {
        setReceipt(null)
        setOcr(null)
      }
      await refreshList()
      setMessage(`${result.deleted} unverified receipt${result.deleted === 1 ? '' : 's'} deleted.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not delete unverified receipts.')
    } finally {
      setBusy(false)
    }
  }

  if (page === 'analysis') return <AnalysisPage onBack={() => setPage('review')} />

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">Personal spending</p>
          <div className="page-heading"><h1>Upload and review</h1><button className="navigation-link" onClick={() => setPage('analysis')}>→ Analyse</button></div>
        </div>
        <p className="subtle">Local OCR · SQLite storage</p>
      </header>

      <form className="upload" onSubmit={upload}>
        <label htmlFor="receipt-file">Receipt file</label>
        <input id="receipt-file" type="file" multiple accept="image/png,image/jpeg,application/pdf" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
        <button disabled={busy}>{busy ? 'Working…' : `Upload and analyse${files.length > 1 ? ` ${files.length} receipts` : ''}`}</button>
        <button type="button" className="delete-unverified" disabled={busy || !receipts.some((item) => item.status !== 'verified')} onClick={() => void removeUnverified()}>Delete unverified receipts</button>
      </form>
      {message && <p className="message" role="status">{message}</p>}

      <section className="workspace">
        <section className="panel list">
          <div className="panel-title"><h2>Recent receipts</h2><button className="text-button" onClick={() => void refreshList()}>Refresh</button></div>
          {receipts.length === 0 ? <p className="empty">No receipts yet.</p> : Object.entries(receiptGroups).map(([day, groupedReceipts]) => (
            <section className="receipt-day" key={day}>
              <h3>{day}</h3>
              <ul>{groupedReceipts.map((item) => (
                <li key={item.id}>
                  <button className={receipt?.id === item.id ? 'selected' : ''} onClick={() => void load(item.id)}>
                    <span>{item.supermarket_name ?? 'Unknown supermarket'}</span><strong>{money(item.total_pence, item.currency)}</strong>
                    <small>{item.status.replace('_', ' ')}</small>
                  </button>
                </li>
              ))}</ul>
            </section>
          ))}
        </section>

        <section className="panel detail">
          {!receipt ? <p className="empty">Select a receipt to see its OCR analysis.</p> : <>
            <div className="panel-title">
              <h2>{(receipt.supermarket_name ?? store) || 'Unknown supermarket'}</h2>
              <div className="detail-actions">
                <div className="mode-switch" aria-label="Receipt view">
                  <button type="button" className={receiptMode === 'compare' ? 'active' : ''} onClick={() => setReceiptMode('compare')}>Compare</button>
                  <button type="button" className={receiptMode === 'details' ? 'active' : ''} onClick={() => setReceiptMode('details')}>Details</button>
                </div>
                <span className={`status ${receipt.status}`}>{receipt.status.replace('_', ' ')}</span>
              </div>
            </div>
            <div className="summary">
              <div><span>Total</span><strong>{money(receipt.total_pence, receipt.currency)}</strong></div>
              <div><span>Voucher</span><strong>{receipt.voucher_pence ? `−${money(receipt.voucher_pence, receipt.currency)}` : '—'}</strong></div>
              {receiptMode === 'details' && <><div><span>OCR confidence</span><strong>{ocr?.confidence === null || !ocr ? '—' : `${Math.round(ocr.confidence * 100)}%`}</strong></div>
              <div><span>Engine</span><strong>{ocr?.engine ?? 'Not run'}</strong></div></>}
            </div>

            {receipt.status === 'needs_review' && <form className="review" onSubmit={save}>
              <h3>Review details</h3>
              <label>Merchant<input value={store} onChange={(event) => setStore(event.target.value)} /></label>
              <label>Expense category<select value={expenseCategoryId} onChange={(event) => setExpenseCategoryId(event.target.value)}><option value="">Uncategorised</option>{expenseCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              <label>Date
                <input
                  type="text"
                  list="receipt-date-candidates"
                  placeholder="DD/MM/YYYY"
                  pattern="\d{2}/\d{2}/\d{4}"
                  value={date}
                  onChange={(event) => setDate(event.target.value)}
                />
                <datalist id="receipt-date-candidates">
                  {(ocr?.output?.parsed.date_candidates ?? []).map((candidate) => <option key={candidate} value={displayDate(candidate)} />)}
                </datalist>
              </label>
              <label>Total<input type="number" min="0" step="0.01" value={total} onChange={(event) => setTotal(event.target.value)} /></label>
              <label>Voucher<input type="number" min="0" step="0.01" value={voucher} onChange={(event) => setVoucher(event.target.value)} /></label>
              <button disabled={busy}>Save changes</button>
              <button type="button" className="secondary" disabled={busy} onClick={() => void verify()}>Verify receipt</button>
            </form>}

            {receipt.status === 'verified' && <p className="subtle">Expense category: {receipt.expense_category_name ?? 'Uncategorised'}</p>}

            {receiptMode === 'details' && ocr?.output?.parsed.warnings?.length ? <div className="warnings"><h3>Review notes</h3><ul>{ocr.output.parsed.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
            <div className={receiptMode === 'compare' ? 'receipt-compare' : ''}>
              <section className="items-section"><h3>Items</h3>
            {receipt.items.length ? <div className="items-table"><table>
              <thead><tr><th>Name</th>{receiptMode === 'details' && <><th>Brand</th><th>Category</th></>}<th>Quantity</th><th>Unit</th><th>Unit price</th><th>Discount</th><th>Original</th></tr></thead>
              <tbody>{receipt.items.map((item, index) => <tr key={`${receipt.id}-${item.id}-${index}`} className={item.unit_price_pence !== null && Math.abs(Math.round(item.quantity * item.unit_price_pence) - item.original_pence) > 1 ? 'requires-review' : ''}>
                  <ItemCell label="Name" value={item.raw_description} editable={receipt.status === 'needs_review'} />
                  {receiptMode === 'details' && <>
                  <BrandCell item={item} editable={receipt.status === 'needs_review'} onChange={(value) => updateItemBrand(index, value)} />
                  <CategoryCell item={item} categories={categories} editable={receipt.status === 'needs_review'} onChange={(value) => updateItemCategory(index, value)} />
                  </>}
                  <ItemCell label="Quantity" value={item.quantity} editable={receipt.status === 'needs_review'} />
                  <ItemCell label="Unit" value={Number.isInteger(item.quantity) ? 'pack' : 'kg'} editable={receipt.status === 'needs_review'} />
                  <ItemCell label="Unit price" value={money(item.unit_price_pence, receipt.currency)} editable={receipt.status === 'needs_review'} />
                  <ItemCell label="Discount" value={item.discount_pence
                    ? `−${money(item.discount_pence, receipt.currency)}${item.discounts.length
                      ? ` · ${item.discounts.map((discount) => discount.reason || discount.source_text).join(' + ')}` : ''}`
                    : '—'} editable={receipt.status === 'needs_review'} />
                  <ItemCell label="Original" value={money(item.original_pence, receipt.currency)} editable={receipt.status === 'needs_review'} />
                </tr>)}</tbody>
              <tfoot><tr>
                <th colSpan={receiptMode === 'details' ? 5 : 3}>Items total</th>
                <td>Original {money(itemsOriginalTotal, receipt.currency)}</td>
                <td>−{money(itemsDiscountTotal, receipt.currency)}</td>
                <td>{receipt.voucher_pence ? `Voucher −${money(receipt.voucher_pence, receipt.currency)} · ` : ''}{money(receipt.total_pence, receipt.currency)}</td>
              </tr></tfoot>
            </table></div> : <p className="empty">No item lines recognised.</p>}</section>
              {receiptMode === 'compare' && <section className="document-panel">
                <h3>OCR receipt area</h3>
                {receipt.source_path?.toLowerCase().endsWith('.pdf')
                  ? <iframe className="document-preview" src={receiptDocumentUrl(receipt.id)} title="Original receipt" />
                  : <div className="receipt-preview-scroll">
                      <img className="receipt-image-preview" src={receiptOCRPreviewUrl(receipt.id, receipt.file_sha256)} alt="Colour receipt with detected OCR boundary" />
                    </div>}
              </section>}
            </div>
            {receiptMode === 'details' && <details><summary>OCR text</summary><pre>{ocr?.output?.text ?? 'No OCR result available.'}</pre></details>}
            {receipt.status !== 'processing' && <button className="danger" disabled={busy} onClick={() => void remove()}>Delete receipt</button>}
          </>}
        </section>
      </section>
    </main>
  )
}

export default App
