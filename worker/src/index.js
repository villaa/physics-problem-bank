// Serves protected problem PDFs only after verifying an access key.
// Route:  GET /problem/:problemId/:filePath?key=XXXX
//   :filePath is the same "solutions/xyz.pdf" style path used in
//   docs/data/problems.json's protected entries (statement.pdf, or
//   solutions/<name>.pdf).
//
// Bindings expected (see wrangler.toml):
//   PROBLEM_KEYS  - KV namespace. One entry per protected problem:
//       key:   problemId
//       value: JSON string {"keyHash": "<sha256 hex of the plaintext key>"}
//   PROTECTED_PDFS - R2 bucket. Objects stored at "<problemId>/<filePath>".

const ALLOWED_ORIGIN = "https://villaa.github.io";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    const match = url.pathname.match(/^\/problem\/([^/]+)\/(.+)$/);
    if (!match) {
      return json({ error: "not_found" }, 404);
    }
    const [, problemId, filePath] = match;
    const key = url.searchParams.get("key") || "";

    const record = await env.PROBLEM_KEYS.get(problemId, "json");
    if (!record) {
      return json({ error: "not_found" }, 404);
    }

    const providedHash = await sha256Hex(key);
    if (!timingSafeEqual(providedHash, record.keyHash)) {
      return json({ error: "invalid_key" }, 403);
    }

    const objectKey = `${problemId}/${filePath}`;
    const object = await env.PROTECTED_PDFS.get(objectKey);
    if (!object) {
      return json({ error: "not_found" }, 404);
    }

    return new Response(object.body, {
      headers: {
        ...corsHeaders(),
        "content-type": "application/pdf",
        "cache-control": "private, no-store",
      },
    });
  },
};

function corsHeaders() {
  return {
    "access-control-allow-origin": ALLOWED_ORIGIN,
    "access-control-allow-methods": "GET, OPTIONS",
  };
}

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(), "content-type": "application/json" },
  });
}

async function sha256Hex(str) {
  const data = new TextEncoder().encode(str);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hashBuffer)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Constant-time-ish string compare to avoid trivial timing leaks.
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}
