import { useCallback, useRef, useState } from "react";
import { uploadCaseFiles } from "../api";
import type { CaseFormData, CaseUploadResult } from "../types";
import { CASE_TYPES, COURT_TYPES, DESIRED_OUTCOMES } from "../types";

interface CaseFormProps {
  onSubmit: (data: CaseFormData) => void;
  disabled: boolean;
}

export function CaseForm({ onSubmit, disabled }: CaseFormProps) {
  const [query, setQuery] = useState("");
  const [courtType, setCourtType] = useState("");
  const [caseType, setCaseType] = useState("");
  const [caseContext, setCaseContext] = useState("");
  const [desiredOutcome, setDesiredOutcome] = useState("");
  const [caseFiles, setCaseFiles] = useState<File[]>([]);
  const [uploadedIds, setUploadedIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState<CaseUploadResult[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) return;
    const pdfs = Array.from(fileList).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf"),
    );
    setCaseFiles((prev) => [...prev, ...pdfs]);
  }, []);

  const removeFile = useCallback((idx: number) => {
    setCaseFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleUpload = useCallback(async () => {
    if (!caseFiles.length) return;
    setUploading(true);
    try {
      const res = await uploadCaseFiles(caseFiles);
      setUploadResults(res.results);
      const ids = res.results
        .filter((r) => r.status === "ok" && r.file_id)
        .map((r) => r.file_id!);
      setUploadedIds((prev) => [...prev, ...ids]);
      setCaseFiles([]);
    } catch (e) {
      setUploadResults([
        {
          filename: "upload",
          status: "error",
          detail: e instanceof Error ? e.message : String(e),
        },
      ]);
    } finally {
      setUploading(false);
    }
  }, [caseFiles]);

  const handleSubmit = useCallback(() => {
    const q = query.trim();
    if (!q) return;
    onSubmit({
      query: q,
      court_type: courtType || null,
      case_type: caseType || null,
      case_context: caseContext.trim() || null,
      desired_outcome: desiredOutcome || null,
      uploaded_file_ids: uploadedIds,
    });
  }, [query, courtType, caseType, caseContext, desiredOutcome, uploadedIds, onSubmit]);

  return (
    <div className="case-form">
      <div className="form-section">
        <label className="form-label" htmlFor="case-query">
          Case Description <span className="required">*</span>
        </label>
        <textarea
          id="case-query"
          className="form-textarea"
          placeholder="Describe your case in detail — facts, parties involved, charges or claims, key circumstances..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={5}
          disabled={disabled}
        />
      </div>

      <div className="form-grid">
        <div className="form-field">
          <label className="form-label" htmlFor="court-type">
            Court Type
          </label>
          <select
            id="court-type"
            className="form-select"
            value={courtType}
            onChange={(e) => setCourtType(e.target.value)}
            disabled={disabled}
          >
            {COURT_TYPES.map((ct) => (
              <option key={ct.value} value={ct.value}>
                {ct.label}
              </option>
            ))}
          </select>
        </div>

        <div className="form-field">
          <label className="form-label" htmlFor="case-type">
            Case Type
          </label>
          <select
            id="case-type"
            className="form-select"
            value={caseType}
            onChange={(e) => setCaseType(e.target.value)}
            disabled={disabled}
          >
            {CASE_TYPES.map((ct) => (
              <option key={ct.value} value={ct.value}>
                {ct.label}
              </option>
            ))}
          </select>
        </div>

        <div className="form-field">
          <label className="form-label" htmlFor="desired-outcome">
            Desired Outcome
          </label>
          <select
            id="desired-outcome"
            className="form-select"
            value={desiredOutcome}
            onChange={(e) => setDesiredOutcome(e.target.value)}
            disabled={disabled}
          >
            {DESIRED_OUTCOMES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-section">
        <label className="form-label" htmlFor="case-context">
          Additional Context
        </label>
        <textarea
          id="case-context"
          className="form-textarea form-textarea--sm"
          placeholder="Any additional background, prior proceedings, specific concerns..."
          value={caseContext}
          onChange={(e) => setCaseContext(e.target.value)}
          rows={3}
          disabled={disabled}
        />
      </div>

      <div className="form-section">
        <label className="form-label">Upload Case Files (PDF)</label>
        <div
          className={`form-dropzone${dragOver ? " form-dropzone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            multiple
            style={{ display: "none" }}
            onChange={(e) => handleFiles(e.target.files)}
          />
          <div className="dropzone-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
          </div>
          <span className="dropzone-text">
            Drop PDF files here or click to browse
          </span>
        </div>

        {caseFiles.length > 0 && (
          <div className="file-list">
            {caseFiles.map((f, i) => (
              <div key={`${f.name}-${i}`} className="file-item">
                <span className="file-icon">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                    <polyline points="14,2 14,8 20,8" />
                  </svg>
                </span>
                <span className="file-name">{f.name}</span>
                <span className="file-size">
                  {(f.size / 1024 / 1024).toFixed(1)} MB
                </span>
                <button
                  type="button"
                  className="file-remove"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  title="Remove"
                >
                  x
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={handleUpload}
              disabled={uploading || disabled}
            >
              {uploading ? "Uploading..." : `Upload ${caseFiles.length} file${caseFiles.length > 1 ? "s" : ""}`}
            </button>
          </div>
        )}

        {uploadedIds.length > 0 && (
          <div className="upload-badge">
            {uploadedIds.length} file{uploadedIds.length > 1 ? "s" : ""} uploaded and indexed
          </div>
        )}

        {uploadResults.length > 0 && (
          <ul className="upload-results">
            {uploadResults.map((r, i) => (
              <li
                key={i}
                className={r.status === "ok" ? "upload-ok" : "upload-err"}
              >
                {r.status === "ok" ? "\u2713" : "\u2717"} {r.filename}
                {r.status === "ok"
                  ? ` — ${r.chunks} sections indexed`
                  : ` — ${r.detail}`}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="form-actions">
        <button
          type="button"
          className="btn-primary"
          onClick={handleSubmit}
          disabled={disabled || !query.trim()}
        >
          {disabled ? (
            <>
              <span className="btn-spinner" /> Analyzing...
            </>
          ) : (
            "Run Analysis"
          )}
        </button>
        <span className="form-hint">
          Best results with case PDFs uploaded to the library.
        </span>
      </div>
    </div>
  );
}
