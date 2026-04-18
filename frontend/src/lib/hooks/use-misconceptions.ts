"use client";

import { useMutation } from "@tanstack/react-query";
import { misconceptionsApi, type MisconceptionReport } from "@/lib/api-client";

export function useMisconceptions() {
  return useMutation<MisconceptionReport, Error, string>({
    mutationFn: (code: string) => misconceptionsApi.analyze(code),
  });
}
