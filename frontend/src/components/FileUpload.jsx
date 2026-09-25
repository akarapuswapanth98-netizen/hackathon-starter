import { useState } from 'react'
import api from '../services/api'

export default function FileUpload({ onUploaded, onError }) {
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [dragOver, setDragOver] = useState(false)

  async function handleFile(file) {
    if (!file) return
    setUploading(true)
    try {
      const res = await api.upload(file)
      setResult(res)
      onUploaded?.(res)
    } catch (err) {
      onError?.(err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div
      onDragOver={e=>{e.preventDefault(); setDragOver(true)}}
      onDragLeave={()=>setDragOver(false)}
      onDrop={e=>{e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files?.[0])}}
      style={{
        border: `2px dashed ${dragOver ? 'var(--primary)' : 'var(--gray-200)'}`,
        borderRadius: '12px',
        padding: '14px',
        background: dragOver ? 'var(--primary-light)' : 'var(--gray-50)',
        transition: 'all 0.2s',
        marginTop: '12px'
      }}
    >
      <div className="card-header" style={{ marginBottom: '6px' }}>📎 File upload <span className="small" style={{ textTransform: 'none', fontWeight: 400, letterSpacing: 0 }}>(optional — RAG / Vision / ML)</span></div>
      <input type="file" onChange={e=>handleFile(e.target.files?.[0])} disabled={uploading} style={{ display: 'block', marginTop: '6px', fontSize: '13px' }} accept=".txt,.md,.csv,.pdf,.jpg,.jpeg,.png,.webp" />
      <div className="small mt-2">Drag & drop or click — Text/PDF → RAG ingestion (if <code>RAG_ENABLED=true</code>) · Image → Vision · CSV → ML</div>
      {uploading && <div className="small mt-2">⏳ Uploading...</div>}
      {result && <pre style={{ marginTop: '10px', fontSize: '11px', background: 'white', padding: '10px', borderRadius: '8px', overflow: 'auto', maxHeight: '140px', border: '1px solid var(--gray-200)' }}>{JSON.stringify(result, null, 2)}</pre>}
    </div>
  )
}
