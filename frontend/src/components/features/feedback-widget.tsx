"use client";

import React, { useState } from "react";
import { MessageSquare, Send, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [sent, setSent] = useState(false);
  const pathname = usePathname();

  const submit = async () => {
    if (!body.trim()) return;
    await fetch("/api/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ route: pathname, body }),
    });
    setSent(true);
    setTimeout(() => {
      setOpen(false);
      setSent(false);
      setBody("");
    }, 2000);
  };

  return (
    <div className="fixed bottom-4 right-4 z-50">
      {open ? (
        <div className="w-72 rounded-lg border border-border bg-card p-4 shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Send feedback</span>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close feedback"
              className="rounded p-0.5 text-muted-foreground hover:bg-accent"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {sent ? (
            <p className="text-sm text-green-600">Thanks! Feedback sent.</p>
          ) : (
            <>
              <Textarea
                placeholder="What's on your mind?"
                value={body}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setBody(e.target.value)}
                rows={3}
                className="mb-2 text-sm"
                aria-label="Feedback message"
              />
              <Button
                size="sm"
                onClick={submit}
                disabled={!body.trim()}
                className="w-full"
              >
                <Send className="mr-1.5 h-3.5 w-3.5" />
                Send
              </Button>
            </>
          )}
        </div>
      ) : (
        <Button
          size="icon"
          variant="outline"
          className="rounded-full shadow-md"
          onClick={() => setOpen(true)}
          aria-label="Open feedback widget"
        >
          <MessageSquare className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
