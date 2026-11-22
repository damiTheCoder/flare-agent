/** Voice replies: same-origin TTS proxy plus text cleanup for speech. */

const MAX_SPEECH_CHARS = 4000;

export async function synthesize(text: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch("/api/tts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: text.slice(0, MAX_SPEECH_CHARS) }),
    signal,
  });
  if (!response.ok) {
    let message = `Voice service error (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: { message?: string } };
      if (body.detail?.message) message = body.detail.message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
  return response.blob();
}

/** Strip markdown so the voice reads prose instead of punctuation. */
export function speechText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " Code block. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/[*_~]/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}
