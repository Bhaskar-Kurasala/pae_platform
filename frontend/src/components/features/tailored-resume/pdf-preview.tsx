"use client";

import { tailoredResumeCopy as copy } from "@/lib/copy/tailored-resume";
import {
  tailoredResumePdfUrl,
  type TailoredResumeResult,
} from "@/lib/hooks/use-tailored-resume";

interface Props {
  result: TailoredResumeResult;
  onClose: () => void;
}

export function PdfPreview({ result, onClose }: Props) {
  const pdfUrl = tailoredResumePdfUrl(result.id);
  const validationOk = result.validation.passed;

  return (
    <div className="resume-preview">
      <div className="resume-head">
        <div>
          <div className="resume-name">{copy.preview.heading}</div>
          <div className="resume-meta">{result.content.summary}</div>
        </div>
        <span className={`rd-badge ${validationOk ? "good" : "warn"}`}>
          {validationOk ? "Verified" : "Review"}
        </span>
      </div>

      <div className="resume-block">
        <h6>Tailored bullets</h6>
        {result.content.bullets.map((b, i) => (
          <div key={i} className="resume-bullet">
            {b.text}
          </div>
        ))}
      </div>

      <div className="resume-block">
        <h6>Skills line</h6>
        <div className="resume-bullet">{result.content.skills.join(", ")}</div>
      </div>

      <div className="resume-block">
        <h6>{copy.preview.coverLetterHeading}</h6>
        <div className="resume-bullet" style={{ whiteSpace: "pre-wrap" }}>
          {result.cover_letter.body}
        </div>
      </div>

      <div className="rd-note">
        <b>Trust check</b>
        <span>
          {validationOk
            ? copy.preview.validationPassed
            : copy.preview.validationWarn}
        </span>
      </div>

      <div className="rd-footer">
        <a
          className="btn primary"
          href={pdfUrl}
          download
          target="_blank"
          rel="noreferrer"
        >
          {copy.preview.downloadButton}
        </a>
        <button type="button" className="btn ghost" onClick={onClose}>
          {copy.preview.closeButton}
        </button>
      </div>
    </div>
  );
}
