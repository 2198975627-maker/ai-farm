const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function fixture() {
  const session = {};
  const requests = [];
  let listener;
  let onRemoved;
  const chrome = {
    runtime: { id: 'fixture-extension', onMessage: { addListener(fn) { listener = fn; } } },
    tabs: { onRemoved: { addListener(fn) { onRemoved = fn; } } },
    storage: { session: {
      async set(values) { Object.assign(session, values); },
      async get(key) { return { [key]: session[key] }; },
      async remove(key) { delete session[key]; },
    } },
  };
  const fetch = async (url, options) => {
    requests.push({ url, options });
    const request = JSON.parse(options.body);
    return { ok: true, json: async () => ({ ok: true, result: request.action === 'gettaskprompt'
      ? { task_id: request.payload.task_id, assigned_to: 'worker' } : { claimed: true } }) };
  };
  const context = vm.createContext({ chrome, fetch, URL });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8'), context);
  const sender = { id: chrome.runtime.id, tab: { id: 1 }, url: 'https://chatgpt.com/' };
  return {
    session, requests, sender,
    send(message, source = sender) { return new Promise(resolve => listener(message, source, resolve)); },
    closeTab() { onRemoved(1); },
  };
}

test('page-script clicks cannot trigger privileged content-script handlers', async () => {
  const elements = new Map();
  let mounted = false;
  let messages = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, { style: {}, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } });
    return elements.get(id);
  };
  const document = {
    getElementById(id) { return mounted ? element(id) : null; },
    createElement() { return { style: {}, innerHTML: '' }; },
    body: { appendChild() { mounted = true; } },
  };
  const context = vm.createContext({
    document, URL, setTimeout() {},
    window: { location: { href: 'https://chatgpt.com/', hash: '' }, prompt() { throw new Error('Untrusted prompt'); } },
    chrome: { runtime: { id: 'fixture', sendMessage(message, callback) { messages++; callback({ ok: false, error: 'Not bound' }); } } },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../browser-extension/content.js'), 'utf8'), context);
  await Promise.resolve();
  const before = messages;
  for (const id of ['bind', 'check', 'sync', 'fill', 'report']) {
    await element(`ai-farm-btn-${id}`).listeners.click({ isTrusted: false });
  }
  assert.equal(messages, before);
});

const bind = { type: 'BIND_TASK', taskId: 'TEST-1', token: 'T'.repeat(43) };

test('unbound tabs cannot fetch latest task or report', async () => {
  const f = fixture();
  for (const type of ['GET_TASK_PROMPT', 'SUBMIT_WORKER_REPORT', 'CLAIM_WORKER_SEND']) {
    assert.equal((await f.send({ type })).ok, false);
  }
  assert.equal(f.requests.length, 0);
});

test('credentials are bound to HTTPS extension sender and tab', async () => {
  const f = fixture();
  for (const sender of [{ ...f.sender, id: 'other' }, { ...f.sender, tab: undefined },
    { ...f.sender, url: 'http://chatgpt.com/' }, { ...f.sender, url: 'https://chatgpt.com.evil.invalid/' }]) {
    assert.equal((await f.send(bind, sender)).ok, false);
  }
  assert.equal(f.requests.length, 0);
  assert.equal((await f.send(bind)).ok, true);
  assert.equal((await f.send({ type: 'GET_TASK_PROMPT', taskId: 'OTHER' })).ok, false);
  assert.equal((await f.send({ type: 'GET_TASK_PROMPT' }, { ...f.sender, tab: { id: 2 } })).ok, false);
  assert.equal((await f.send({ type: 'GET_TASK_PROMPT' }, { ...f.sender, url: 'https://grok.com/' })).ok, false);
});

test('credentials go only in Authorization and reports use bound identity', async () => {
  const f = fixture();
  await f.send(bind);
  assert.equal((await f.send({ type: 'SUBMIT_WORKER_REPORT', taskId: 'TEST-1', workerId: 'owner', text: 'Fixture conclusion' })).ok, true);
  for (const request of f.requests) {
    assert.equal(request.options.headers.Authorization, `Bearer ${bind.token}`);
    assert.equal(request.options.credentials, 'omit');
    assert.equal(request.options.redirect, 'error');
    assert.equal(request.url.includes(bind.token), false);
    assert.equal(request.options.body.includes(bind.token), false);
  }
  assert.equal(JSON.parse(f.requests.at(-1).options.body).payload.sender_id, 'worker');
  f.closeTab();
  assert.equal((await f.send({ type: 'GET_TASK_PROMPT' })).ok, false);
});

test('send reservation is separate from prompt read and unknown operations reject', async () => {
  const f = fixture();
  await f.send(bind);
  await f.send({ type: 'CLAIM_WORKER_SEND', taskId: 'TEST-1' });
  assert.equal(JSON.parse(f.requests.at(-1).options.body).action, 'courierclaim');
  assert.equal((await f.send({ type: 'EXECUTE_MODEL' })).ok, false);
});
