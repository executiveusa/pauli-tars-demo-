import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const stress = process.env.STRESS_URL || 'https://browser-use.github.io/stress-tests/';
const bars = process.env.BARS_PAGE_URL;
const browser = await chromium.launch({headless:true});
const page = await browser.newPage({viewport:{width:390,height:844}});
const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
try {
  await page.goto(stress,{waitUntil:'domcontentloaded',timeout:30000});
  assert.match(await page.title(),/Browser-Use Stress Tests/i);
  const links=await page.locator('a[href]').count(); assert.ok(links>=5,`stress target rendered only ${links} links`);
  assert.ok(await page.locator('a[href*="challenge"], a[href*="index.html"]').count()>=1,'stress challenge entry is missing');
  if(bars){
    await page.goto(bars,{waitUntil:'domcontentloaded',timeout:30000});
    const brief=page.locator('#brief'), ask=page.locator('#askBtn'), deploy=page.locator('#deployBtn');
    await brief.waitFor({state:'visible'}); await ask.waitFor({state:'visible'}); await deploy.waitFor({state:'visible'});
    const box=await brief.boundingBox(); assert.ok(box&&box.width>=150&&box.height>=20,'mobile input is not tappable');
    await brief.fill('page gate probe'); assert.equal(await brief.inputValue(),'page gate probe');
    assert.equal(errors.length,0,`page errors: ${errors.join(' | ')}`);
  }
  console.log(`PASS page gate stress=${stress}${bars?` bars=${bars}`:' contract-only'}`);
} finally { await browser.close(); }
