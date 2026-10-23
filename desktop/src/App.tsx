import { FormEvent, useEffect, useState } from 'react'
import {
  getOCR,
  getReceipt,
  listReceipts,
  runOCR,
  saveReview,
  uploadReceipt,
  verifyReceipt,
  type OCRRun,
  type Receipt,
} from './api'

function money(value: number | null, currency = 'GBP') {
  if (value === null) return '—'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(value / 100)
}

function App() {
  const [receipts, setReceipts] = useState<Omit<Receipt, 'items'>[]>([])
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [ocr, setOcr] = useState<OCRRun | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [store, setStore] = useState('')
  const [date, setDate] = useState('')
  const [total, setTotal] = useState('')

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

  useEffect(() => { void refreshList() }, [])

  useEffect(() => {
    if (!receipt) return
    setStore(ocr?.output?.parsed.supermarket_name ?? '')
    setDate(receipt.purchase_date ?? '')
    setTotal(receipt.total_minor === null ? '' : (receipt.total_minor / 100).toFixed(2))
  }, [receipt, ocr])

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!file) {
      setMessage('Choose a JPG, PNG, or PDF receipt first.')
      return
    }
    setBusy(true)
    setMessage('Uploading and reading receipt…')
    try {
      const created = await uploadReceipt(file)
      await runOCR(created.id)
      await refreshList()
      await load(created.id)
      setFile(null)
      setMessage('Receipt saved and analysed.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Upload failed.')
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
        purchase_date: date || null,
        total_minor: total ? Math.round(Number(total) * 100) : null,
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
      setReceipt(await verifyReceipt(receipt.id))
      await refreshList()
      setMessage('Receipt verified.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not verify this receipt.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">Grocery receipts</p>
          <h1>Upload and review</h1>
        </div>
        <p className="subtle">Local OCR · SQLite storage</p>
      </header>

      <form className="upload" onSubmit={upload}>
        <label htmlFor="receipt-file">Receipt file</label>
        <input id="receipt-file" type="file" accept="image/png,image/jpeg,application/pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <button disabled={busy}>{busy ? 'Working…' : 'Upload and analyse'}</button>
      </form>
      {message && <p className="message" role="status">{message}</p>}

      <section className="workspace">
        <section className="panel list">
          <div className="panel-title"><h2>Recent receipts</h2><button className="text-button" onClick={() => void refreshList()}>Refresh</button></div>
          {receipts.length === 0 ? <p className="empty">No receipts yet.</p> : (
            <ul>
              {receipts.map((item) => (
                <li key={item.id}>
                  <button className={receipt?.id === item.id ? 'selected' : ''} onClick={() => void load(item.id)}>
                    <span>Receipt #{item.id}</span><strong>{money(item.total_minor, item.currency)}</strong>
                    <small>{item.purchase_date ?? 'No date'} · {item.status.replace('_', ' ')}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel detail">
          {!receipt ? <p className="empty">Select a receipt to see its OCR analysis.</p> : <>
            <div className="panel-title"><h2>Receipt #{receipt.id}</h2><span className={`status ${receipt.status}`}>{receipt.status.replace('_', ' ')}</span></div>
            <div className="summary">
              <div><span>Total</span><strong>{money(receipt.total_minor, receipt.currency)}</strong></div>
              <div><span>OCR confidence</span><strong>{ocr?.confidence === null || !ocr ? '—' : `${Math.round(ocr.confidence * 100)}%`}</strong></div>
              <div><span>Engine</span><strong>{ocr?.engine ?? 'Not run'}</strong></div>
            </div>

            {receipt.status === 'needs_review' && <form className="review" onSubmit={save}>
              <h3>Review details</h3>
              <label>Supermarket<input value={store} onChange={(event) => setStore(event.target.value)} /></label>
              <label>Date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
              <label>Total<input type="number" min="0" step="0.01" value={total} onChange={(event) => setTotal(event.target.value)} /></label>
              <button disabled={busy}>Save changes</button>
              <button type="button" className="secondary" disabled={busy} onClick={() => void verify()}>Verify receipt</button>
            </form>}

            {ocr?.output?.parsed.warnings?.length ? <div className="warnings"><h3>Review notes</h3><ul>{ocr.output.parsed.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
            <h3>Items</h3>
            {receipt.items.length ? <div className="items">{receipt.items.map((item) => <div key={item.id}><span>{item.quantity} × {item.raw_description}</span><strong>{money(item.line_total_minor, receipt.currency)}</strong></div>)}</div> : <p className="empty">No item lines recognised.</p>}
            <details><summary>OCR text</summary><pre>{ocr?.output?.text ?? 'No OCR result available.'}</pre></details>
          </>}
        </section>
      </section>
    </main>
  )
}

export default App
