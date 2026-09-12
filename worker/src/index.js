// Serves protected SOLUTION PDFs after redeeming a one-time-use key.
// Problem statements are always public - served directly by GitHub Pages,
// never through this Worker. Only a protected problem's solutions[] PDFs
// live in R2 and require a key.
//
// Route: POST /problem/:problemId/redeem
//   Body (JSON): { "key": "<plaintext key>", "files": ["solutions/xyz.pdf", ...] }
//   On a valid, unused key: removes it from the pool (one-time use) and
//   returns the requested files, base64-encoded, in one response - so a
//   single redemption unlocks every solution method for that problem at
//   once, rather than racing the pool across separate per-file requests.
//
// Bindings (see wrangler.toml):
//   PROBLEM_KEYS   - KV namespace. One entry per protected problem:
//       key:   problemId
//       value: JSON {"keyHashes": ["<sha256 hex>", ...]}  (one-time-use pool)
//   PROTECTED_PDFS - R2 bucket. Objects stored at "<problemId>/<filePath>".

const ALLOWED_ORIGIN = "https://villaa.github.io";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    const match = url.pathname.match(/^\/problem\/([^/]+)\/redeem$/);
    if (!match || request.method !== "POST") {
      return json({ error: "not_found" }, 404);
    }
    const [, problemId] = match;

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid_request" }, 400);
    }
    const key = typeof body.key === "string" ? body.key : "";
    const files = Array.isArray(body.files) ? body.files.map(String) : [];
    if (!key || files.length === 0) {
      return json({ error: "invalid_request" }, 400);
    }

    const record = await env.PROBLEM_KEYS.get(problemId, "json");
    const keyHashes = (record && record.keyHashes) || [];
    if (keyHashes.length === 0) {
      return json({ error: "not_found" }, 404);
    }

    const providedHash = await sha256Hex(key);
    const idx = keyHashes.indexOf(providedHash);
    if (idx === -1) {
      return json({ error: "invalid_key" }, 403);
    }

    // Consume the key (remove it from the pool) before releasing anything.
    const remaining = keyHashes.slice(0, idx).concat(keyHashes.slice(idx + 1));
    await env.PROBLEM_KEYS.put(problemId, JSON.stringify({ keyHashes: remaining }));

    const result = {};
    for (const filePath of files) {
      const obj = await env.PROTECTED_PDFS.get(`${problemId}/${filePath}`);
      if (obj) {
        result[filePath] = bytesToBase64(new Uint8Array(await obj.arrayBuffer()));
      }
    }

    return json({ files: result }, 200);
  },
};

function corsHeaders() {
  return {
    "access-control-allow-origin": ALLOWED_ORIGIN,
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "Content-Type",
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

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}
