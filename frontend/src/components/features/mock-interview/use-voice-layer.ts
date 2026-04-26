"use client";

/**
 * Web Speech API STT + TTS hook for the mock interview voice layer.
 *
 * Browser-only. Falls back gracefully when SpeechRecognition is unavailable
 * (Firefox, older Safari) — caller should prompt the user to switch to text.
 *
 * Key UX rules baked in:
 *   - `timeToFirstWordMs` is recorded from start-of-listen to first non-empty
 *     interim transcript. The Scorer + PatternDetector use this number.
 *   - TTS for the interviewer's reply uses the browser's SpeechSynthesis API
 *     by default. If `process.env.NEXT_PUBLIC_USE_SERVER_TTS === "true"`,
 *     the caller is expected to pipe an audio Blob URL into `playUrl`.
 *   - We do NOT store audio. Only the transcript hits the server.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { mockAnalytics } from "./analytics";
import { COPY } from "./copy";

// SpeechRecognition cross-browser shim.
type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: ((this: unknown) => void) | null;
  onresult:
    | ((this: unknown, event: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void)
    | null;
  onerror: ((this: unknown, event: { error: string }) => void) | null;
  onend: ((this: unknown) => void) | null;
  start: () => void;
  stop: () => void;
};

interface SpeechRecognitionConstructor {
  new (): SpeechRecognitionLike;
}

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  const ctor =
    (w.SpeechRecognition as SpeechRecognitionConstructor | undefined) ??
    (w.webkitSpeechRecognition as SpeechRecognitionConstructor | undefined);
  return ctor ?? null;
}

export interface VoiceLayerState {
  supported: boolean;
  listening: boolean;
  interimTranscript: string;
  finalTranscript: string;
  timeToFirstWordMs: number | null;
  error: string | null;
}

export interface VoiceLayerControls {
  start: () => void;
  stop: () => void;
  reset: () => void;
  speak: (text: string) => void;
  cancelSpeech: () => void;
}

export function useVoiceLayer(): VoiceLayerState & VoiceLayerControls {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interimTranscript, setInterim] = useState("");
  const [finalTranscript, setFinal] = useState("");
  const [timeToFirstWordMs, setTtfw] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const startedAtRef = useRef<number>(0);
  const ttfwSetRef = useRef<boolean>(false);

  // Construct the recognizer lazily; some browsers throw on construction in
  // SSR even if the global is shimmed.
  useEffect(() => {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setSupported(false);
      return;
    }
    const recognizer = new Ctor();
    recognizer.continuous = true;
    recognizer.interimResults = true;
    recognizer.lang = "en-US";
    recognitionRef.current = recognizer;
    setSupported(true);

    return () => {
      try {
        recognizer.stop();
      } catch {
        /* ignore */
      }
    };
  }, []);

  const start = useCallback(() => {
    const recognizer = recognitionRef.current;
    if (!recognizer) {
      setError(COPY.errors.sttUnsupported);
      mockAnalytics.voiceFallbackToText({ reason: "stt_unsupported" });
      return;
    }
    setError(null);
    setInterim("");
    setFinal("");
    setTtfw(null);
    ttfwSetRef.current = false;
    startedAtRef.current = Date.now();

    recognizer.onstart = () => {
      setListening(true);
    };
    recognizer.onresult = (event: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => {
      let interim = "";
      let appended = "";
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          appended += transcript;
        } else {
          interim += transcript;
        }
      }
      // First non-empty interim → record time-to-first-word.
      if (!ttfwSetRef.current && (interim.trim() || appended.trim())) {
        ttfwSetRef.current = true;
        setTtfw(Date.now() - startedAtRef.current);
      }
      setInterim(interim);
      if (appended) {
        setFinal((prev) => (prev ? `${prev} ${appended}` : appended).trim());
      }
    };
    recognizer.onerror = (event: { error: string }) => {
      const reason = event.error;
      if (reason === "not-allowed" || reason === "service-not-allowed") {
        setError(COPY.errors.micDenied);
        mockAnalytics.voiceFallbackToText({ reason: "mic_denied" });
      } else {
        setError(`Voice error: ${reason}`);
        mockAnalytics.voiceFallbackToText({ reason });
      }
      setListening(false);
    };
    recognizer.onend = () => {
      setListening(false);
    };

    try {
      recognizer.start();
    } catch (exc) {
      // Some Chromium builds throw "InvalidStateError" if start is called twice.
      setError("Voice input couldn't start. Try again.");
      mockAnalytics.voiceFallbackToText({
        reason: exc instanceof Error ? exc.name : "start_failed",
      });
    }
  }, []);

  const stop = useCallback(() => {
    const recognizer = recognitionRef.current;
    if (recognizer) {
      try {
        recognizer.stop();
      } catch {
        /* ignore */
      }
    }
    setListening(false);
  }, []);

  const reset = useCallback(() => {
    stop();
    setInterim("");
    setFinal("");
    setTtfw(null);
    ttfwSetRef.current = false;
    setError(null);
  }, [stop]);

  // ── TTS ────────────────────────────────────────────────────────────
  const speak = useCallback((text: string) => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    if (!text.trim()) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = "en-US";
      utter.rate = 1.05;
      utter.pitch = 1.0;
      window.speechSynthesis.speak(utter);
    } catch {
      /* TTS optional — silent fail */
    }
  }, []);

  const cancelSpeech = useCallback(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* ignore */
    }
  }, []);

  return {
    supported,
    listening,
    interimTranscript,
    finalTranscript,
    timeToFirstWordMs,
    error,
    start,
    stop,
    reset,
    speak,
    cancelSpeech,
  };
}
