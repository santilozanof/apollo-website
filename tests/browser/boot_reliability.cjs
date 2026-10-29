/* The app must become usable even when a noncritical image delays load. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const origin=process.env.APOLLO_TEST_URL || 'http://127.0.0.1:8891';

(async()=>{
 const browser=await chromium.launch({headless:true,
   executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  for(const viewport of [{width:1440,height:900},{width:390,height:844}]){
   const mobile=viewport.width<500;
   const context=await browser.newContext({viewport,isMobile:mobile,hasTouch:mobile});
   const page=await context.newPage();
   const failures=[];
   page.on('pageerror',error=>failures.push(error.message));
   await page.route('**/__apollo_boot_hold.png',route=>new Promise(resolve=>{
     page.once('close',resolve);
   }));
   await page.route(origin+'/',async route=>{
     const response=await route.fetch();
     const body=(await response.text()).replace('</body>',
       '<img src="/__apollo_boot_hold.png" alt="" width="1" height="1"></body>');
     await route.fulfill({response,body});
   });
   await page.goto(origin,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>!document.documentElement.classList.contains('apollo-booting')
     && !document.documentElement.classList.contains('apollo-security-pending'),null,{timeout:7000});
   assert.equal(await page.evaluate(()=>document.readyState),'interactive');
   await page.evaluate(()=>window.openSettings());
   assert.equal(await page.locator('#settingsView').isVisible(),true);
   assert.deepEqual(failures,[]);
   console.log(`${mobile?'iPhone':'desktop'} boot fallback passed with delayed image`);
   await context.close();
  }
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
