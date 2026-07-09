// netlify/functions/github.js
// Middleman between Phoenix frontend and GitHub API
// Keeps GH_TOKEN hidden from the browser

const REPO   = "gg230031/phoenix-cricket";
const BRANCH = "main";
const TOKEN  = process.env.GH_TOKEN;

exports.handler = async (event) => {
  // Only allow POST requests
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method not allowed" };
  }

  const { action, path, content, message } = JSON.parse(event.body || "{}");

  const headers = {
    Authorization: `token ${TOKEN}`,
    Accept: "application/vnd.github.v3+json",
    "Content-Type": "application/json",
  };

  try {
    // ── READ a file from GitHub ───────────────────────────────────────────────
    if (action === "read") {
      const res  = await fetch(
        `https://api.github.com/repos/${REPO}/contents/${path}?ref=${BRANCH}`,
        { headers }
      );
      if (!res.ok) throw new Error(`GitHub read failed: ${res.status}`);
      const data = await res.json();
      const decoded = Buffer.from(data.content, "base64").toString("utf8");
      return {
        statusCode: 200,
        headers: { "Access-Control-Allow-Origin": "*" },
        body: JSON.stringify({ content: decoded, sha: data.sha }),
      };
    }

    // ── WRITE a file to GitHub ────────────────────────────────────────────────
    if (action === "write") {
      // First get current SHA
      const getRes = await fetch(
        `https://api.github.com/repos/${REPO}/contents/${path}?ref=${BRANCH}`,
        { headers }
      );
      const getData = await getRes.json();
      const sha = getData.sha;

      // Write new content
      const putRes = await fetch(
        `https://api.github.com/repos/${REPO}/contents/${path}`,
        {
          method: "PUT",
          headers,
          body: JSON.stringify({
            message: message || "Phoenix: Update file",
            content: Buffer.from(content).toString("base64"),
            sha,
            branch: BRANCH,
          }),
        }
      );
      if (!putRes.ok) throw new Error(`GitHub write failed: ${putRes.status}`);
      return {
        statusCode: 200,
        headers: { "Access-Control-Allow-Origin": "*" },
        body: JSON.stringify({ success: true }),
      };
    }

    return { statusCode: 400, body: "Unknown action" };

  } catch (err) {
    return {
      statusCode: 500,
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify({ error: err.message }),
    };
  }
};
