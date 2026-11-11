---
name: cdp-browser
description: Read a logged-in web page through the owner's own Chromium browser over the Chrome DevTools Protocol, in a background tab, using their saved sign-ins. Use when a page needs a login and WebFetch cannot read it, and only in an interactive session the owner is watching.
---

# Browser over CDP

Optional. Only for a browser the owner started with remote debugging on, and only on their say-so. The port
is the owner's choice; this recipe uses `$CDP_PORT` (for example 9222). Anyone who can reach that port can
drive the browser, so it must listen on 127.0.0.1 only.

## 1. Check the port

```bash
curl -s "http://127.0.0.1:${CDP_PORT:-9222}/json/version" | head -5
```

No answer: do not start a browser yourself. Put the link in your reply for the owner.

## 2. Read a page in a background tab (node, raw CDP)

```javascript
// cdp-read.js   node cdp-read.js "<url>" '<js expression>'
const WebSocket = require("ws");
const port = process.env.CDP_PORT || 9222;
const [url, expr] = process.argv.slice(2);
(async () => {
  const ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  let id = 0; const pending = {};
  const send = (method, params, sessionId) => new Promise(r => { const i = ++id; pending[i] = r;
    ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
  ws.on("message", m => { const d = JSON.parse(m); if (d.id && pending[d.id]) pending[d.id](d); });
  ws.on("open", async () => {
    const { result: { targetId } } = await send("Target.createTarget", { url, background: true });
    const { result: { sessionId } } = await send("Target.attachToTarget", { targetId, flatten: true });
    await new Promise(r => setTimeout(r, 4000));
    const out = await send("Runtime.evaluate", { expression: expr || "document.body.innerText.slice(0,20000)",
      returnByValue: true, awaitPromise: true }, sessionId);
    console.log(out.result && out.result.result ? out.result.result.value : JSON.stringify(out));
    await send("Target.closeTarget", { targetId });
    ws.close();
  });
})();
```

## Rules

- Read only by default. Clicking, typing and submitting follow the same send gate as email: the owner's yes.
- Always close the tab you opened. Never sign out, change a password, or touch account settings.
- Never type a password or a card number.
