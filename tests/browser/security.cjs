/* Isolated local fixture; no real passkeys, accounts or production data. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1280, height: 850}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.APOLLO_TEST_URL || 'http://localhost:8890', {waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    await page.evaluate(() => window.openSettings());
    await page.locator('.apollo-settings-disclosure').filter({hasText:'Privacy & Security · Tab Locks'}).click();
    await page.locator('#apolloSecuritySettings').getByPlaceholder('Operator setup token').fill('fixture-only-operator-token');
    await page.locator('#apolloSecuritySettings').getByPlaceholder('New passphrase (16+ characters)').fill('browser fixture passphrase 1234');
    await page.getByRole('button', {name:'Set up security'}).click();
    await page.locator('.apollo-security-codes').waitFor();
    assert.equal(await page.locator('#apolloSecuritySettings').getByPlaceholder('Operator setup token').count(), 0);
    assert.equal(await page.getByRole('button', {name:'New recovery codes'}).count(), 1);
    assert.equal(await page.getByText('Chat', {exact:true}).count() > 0, true);
    await page.locator('input[data-resource="chat"]').check();
    await page.locator('select[data-resource="chat"]').selectOption('5m');
    await page.getByRole('button', {name:'Save privacy settings'}).click();
    await page.waitForTimeout(250);
    const blocked = await page.evaluate(async () => {
      const response = await fetch('/api/chats'); return {status: response.status, body: await response.json()};
    });
    assert.equal(blocked.status, 423);
    assert.equal(blocked.body.resource, 'chat');
    await page.getByRole('button', {name:'Apollo', exact:true}).first().click();
    await page.locator('#apolloSecurityTitle').getByText('Unlock Chat').waitFor();
    assert.equal(await page.locator('#apolloView').isVisible(), false);
    await page.locator('#apolloSecuritySecret').fill('browser fixture passphrase 1234');
    await page.getByRole('button', {name:'Unlock with passphrase'}).click();
    await page.waitForFunction(() => !document.body.classList.contains('apollo-security-conceal'));
    assert.equal(await page.locator('#apolloView').isVisible(), true);
    const allowed = await page.evaluate(async () => (await fetch('/api/chats')).status);
    assert.equal(allowed, 200);
    const cdp = await context.newCDPSession(page);
    await cdp.send('WebAuthn.enable');
    await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {protocol: 'ctap2', transport: 'internal',
      hasResidentKey: true, hasUserVerification: true, isUserVerified: true,
      automaticPresenceSimulation: true}});
    await page.evaluate(() => window.openSettings());
    await page.getByRole('button', {name:'Add a passkey'}).click();
    await page.getByText('Passkey added.', {exact:true}).waitFor({timeout:5000});
    await page.evaluate(async () => fetch('/api/security/revoke', {method:'POST',
      headers:{'Content-Type':'application/json','X-Apollo-Request':'security'}, body:JSON.stringify({resource:'chat'})}));
    await page.getByRole('button', {name:'Apollo', exact:true}).first().click();
    await page.locator('#apolloSecurityTitle').getByText('Unlock Chat').waitFor();
    await page.getByRole('button', {name:'Unlock with passkey'}).click();
    await page.waitForFunction(() => !document.body.classList.contains('apollo-security-conceal'));
    assert.equal(await page.evaluate(async () => (await fetch('/api/chats')).status), 200);
    await page.evaluate(() => apolloAddMessage('assistant', 'Private fixture response'));
    await page.evaluate(async () => fetch('/api/security/revoke', {method:'POST',
      headers:{'Content-Type':'application/json','X-Apollo-Request':'security'}, body:JSON.stringify({resource:'chat'})}));
    await page.waitForFunction(() => document.body.classList.contains('apollo-security-conceal'), null, {timeout:7000});
    assert.equal(await page.locator('#apolloMessages').getByText('Private fixture response').count(), 0);
    assert.equal(await page.evaluate(async () => (await fetch('/api/chats')).status), 423);
    await page.evaluate(() => window.openSettings());
    await page.locator('select[data-resource="chat"]').selectOption('leave');
    await page.getByRole('button', {name:'Save privacy settings'}).click();
    await page.waitForTimeout(200);
    await page.getByRole('button', {name:'Apollo', exact:true}).first().click();
    await page.locator('#apolloSecurityTitle').getByText('Unlock Chat').waitFor();
    await page.getByRole('button', {name:'Unlock with passkey'}).click();
    await page.waitForFunction(() => !document.body.classList.contains('apollo-security-conceal'));
    await page.evaluate(() => window.openHome());
    await page.waitForFunction(async () => (await fetch('/api/chats')).status === 423);
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
    assert.deepEqual(errors, []);
    console.log('Security enrollment, API block, passphrase/passkey, revoke, relock-on-leave and refresh passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
