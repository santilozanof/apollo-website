/* Visual and accessibility checks against an enrolled, isolated local fixture. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.APOLLO_TEST_URL || 'http://localhost:8905';
(async () => {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
      const mobile = viewport.width < 500;
      const context = await browser.newContext({viewport,isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base,{waitUntil:'domcontentloaded'});
      await page.waitForFunction(() => !document.documentElement.classList.contains('apollo-security-pending'));
      await page.evaluate(() => window.openSettings());
      await page.locator('.apollo-settings-disclosure').filter({hasText:'Privacy & Security'}).click();
      await page.getByRole('button',{name:'Verify to manage security'}).click();
      await page.getByText('Verify security settings',{exact:true}).waitFor();
      assert.equal(await page.locator('#apolloDeviceUnlock').isVisible(),true);
      assert.equal(await page.locator('#apolloSecretMethods').evaluate(node => node.open),false);
      for (const theme of ['light','dark']) {
        await page.evaluate(theme => document.documentElement.setAttribute('data-theme',theme),theme);
        await page.screenshot({path:`/private/tmp/apollo-security-unlock-${mobile?'iphone':'desktop'}-${theme}.png`});
      }
      await page.locator('#apolloSecretMethods summary').focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('#apolloSecretMethods').evaluate(node => node.open),true);
      assert.equal(await page.locator('#apolloSecuritySecret').evaluate(node => getComputedStyle(node).animationName),'none');
      await page.locator('#apolloSecuritySecret').fill('browser fixture passphrase 1234');
      await page.getByRole('button',{name:'Unlock with passphrase'}).click();
      await page.waitForFunction(() => !document.body.classList.contains('apollo-security-conceal'));
      for (const heading of ['Security overview','Tab Locks','Chat Privacy','Credentials & Recovery']) {
        await page.getByRole('heading',{name:heading,exact:true}).waitFor();
      }
      assert.equal(await page.locator('select[data-resource="studio"]').isVisible(),false);
      for (const theme of ['light','dark']) {
        await page.evaluate(theme => document.documentElement.setAttribute('data-theme',theme),theme);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.screenshot({path:`/private/tmp/apollo-security-settings-${mobile?'iphone':'desktop'}-${theme}.png`});
        await page.locator('#apolloSecuritySettings').screenshot({path:`/private/tmp/apollo-security-groups-${mobile?'iphone':'desktop'}-${theme}.png`});
      }
      await page.getByRole('button',{name:'Verify again for changes'}).focus();
      assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('apollo-security-verify')),true);
      assert.deepEqual(errors,[]);
      console.log(`${mobile?'iPhone':'desktop'} security unlock and settings passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
