import {expect,test} from '@playwright/test';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC';
const status={configured:true,model:'vision-test',backend:'custom',destination:'https://vision.example/v1',binding:'a'.repeat(64),review_token:'t'.repeat(32),local:false,selected_turn:true,session_id:'image_session'};
const result={ok:true,response:'A test screenshot.',model:status.model,backend:status.backend,destination:status.destination,local:false};
test('training and cost confirmations are independent, transmitted and reset for the next draft',async({page})=>{
  const images:any[]=[],prepares:string[]=[];
  let binding='a'.repeat(64);
  // Refresh vision destination asks prepare again with `?refresh_catalog=true`
  // (composer-images.tsx), so the route takes the query too: a glob ending in
  // `prepare` lets that request through to the fixture hub, which has no vision model.
  await page.route(/\/api\/vlm\/composer\/prepare(\?|$)/,route=>{prepares.push(route.request().url());return route.fulfill({json:{...status,binding,selection_requirements:[
    {needs:'acknowledge_training',message:'Images may be used for training.'},
    {needs:'confirm_expensive',message:'Output costs $80 per million tokens.'},
  ]}});});
  await page.route('**/api/vlm/composer/describe-prepared',route=>{images.push(route.request().postDataJSON());return route.fulfill({json:result});});
  await page.goto('/v2/chat?demo=1');
  const attach=()=>page.getByLabel('Attach images',{exact:true}).setInputFiles({name:'consent.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  const send=page.getByRole('button',{name:'Send',exact:true});
  const training=page.getByRole('checkbox',{name:/Training use:/});
  const cost=page.getByRole('checkbox',{name:/Cost confirmation:/});
  await attach();
  await expect(training).not.toBeChecked();await expect(cost).not.toBeChecked();
  await page.locator('[data-composer]').fill('Describe screenshot');
  await page.getByRole('checkbox',{name:/Send these images and the assembled conversation prompt to/}).check();
  await expect(send).toBeDisabled();
  await training.check();await expect(send).toBeDisabled();
  await cost.check();await send.click();
  await expect(page.getByText('A test screenshot.',{exact:true})).toBeVisible();
  expect(images).toHaveLength(1);
  expect(images[0]).toMatchObject({expected_binding:binding,review_token:status.review_token,agent:'jarvis',remote_ack:true,acknowledge_training:true,confirm_expensive:true,selected_turn:true,session_id:'image_session'});
  expect(images[0]).not.toHaveProperty('selection_requirements');
  await attach();
  await expect(training).not.toBeChecked();await expect(cost).not.toBeChecked();
  await training.check();await cost.check();
  binding='b'.repeat(64);
  await page.getByRole('button',{name:'Refresh vision destination'}).click();
  await expect.poll(()=>prepares.some(url=>url.includes('refresh_catalog=true'))).toBe(true);
  await expect(training).not.toBeChecked();await expect(cost).not.toBeChecked();
  await expect(send).toBeDisabled();
  expect(images).toHaveLength(1);
});
test('choose paste drop, explicit remote consent, vision provenance and unchanged text chat',async({page})=>{
  const images:any[]=[],texts:any[]=[];
  await page.route('**/api/vlm/composer/prepare',route=>route.fulfill({json:status}));
  await page.route('**/api/vlm/composer/describe-prepared',route=>{images.push(route.request().postDataJSON());return route.fulfill({json:result});});
  await page.route('**/chat/stream',route=>{texts.push(route.request().postDataJSON());return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"start","agent":"jarvis"}\n\ndata: {"type":"end","agent":"jarvis","text":"Text remains text."}\n\n'});});
  await page.goto('/one/v2/chat?demo=1');
  await page.getByLabel('Attach images',{exact:true}).setInputFiles({name:'chosen.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  await expect(page.getByAltText('chosen.png',{exact:true})).toBeVisible();
  for(const type of ['paste','drop'])await page.locator('[data-composer]').evaluate((element,{type,png})=>{
    const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],type+'.png',{type:'image/png'}));
    const event=type==='paste'?new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}):new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true});
    element.dispatchEvent(event);
  },{type,png});
  await expect(page.getByAltText('paste.png',{exact:true})).toBeVisible();await expect(page.getByAltText('drop.png',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Remove chosen.png'}).click();
  await expect(page.getByAltText('chosen.png',{exact:true})).toHaveCount(0);
  await page.locator('[data-composer]').fill('Describe screenshot');
  await expect(page.getByRole('button',{name:'Send',exact:true})).toBeDisabled();expect(images).toHaveLength(0);
  await page.getByRole('checkbox',{name:/Send these images and the assembled conversation prompt to https:\/\/vision.example/}).check();
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await expect(page.getByText('A test screenshot.',{exact:true})).toBeVisible();
  // The Ledger vision turn (PHASE_B_PLAN.md §5.3): "Vision", titled "Vision analysis", then where
  // it actually ran — model, backend and destination as identifiers, and remote.
  const vision=page.locator('[data-turn="vision"]').filter({hasText:'A test screenshot.'});
  await expect(vision.getByTitle('Vision analysis',{exact:true})).toHaveText('Vision');
  await expect(vision.locator('code')).toHaveText(['vision-test','custom',status.destination]);
  await expect(vision).toContainText(`vision-test · custom · ${status.destination} · remote`);
  expect(images).toHaveLength(1);expect(images[0].images).toHaveLength(2);expect(images[0]).toMatchObject({prompt:'Describe screenshot',expected_destination:status.destination,review_token:status.review_token,agent:'jarvis',remote_ack:true});
  expect(texts).toHaveLength(0);
  await page.locator('[data-composer]').fill('ordinary message');await page.getByRole('button',{name:'Send',exact:true}).click();
  await expect(page.getByText('Text remains text.',{exact:true})).toBeVisible();
  // an ordinary text turn: no image field rides along; the HUD asks every text turn for its tool
  // events (H137, turn-tools.tsx), as the unit test of the same flow pins
  expect(texts).toEqual([{message:'ordinary message',agent:'jarvis',tool_events:true}]);
});
test('stale destination fails visibly and a cancelled late vision result is ignored',async({page})=>{
  let calls=0,release:()=>void=()=>{};
  await page.route('**/api/vlm/composer/prepare',route=>route.fulfill({json:{...status,local:true}}));
  await page.route('**/api/vlm/composer/describe-prepared',async route=>{
    if(calls++===0)return route.fulfill({status:409,json:{error:'Vision destination changed; review it again'}});
    await new Promise<void>(resolve=>release=resolve);await route.fulfill({json:result}).catch(()=>{});
  });
  await page.goto('/v2/chat?demo=1');
  const choose=async()=>{await page.getByLabel('Attach images',{exact:true}).setInputFiles({name:'shot.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await page.getByRole('button',{name:'Send',exact:true}).click();};
  await choose();await expect(page.getByText(/Vision analysis failed: Vision destination changed/)).toBeVisible();
  // the pending vision turn's one control (§5.3)
  const stop=page.getByRole('button',{name:'Stop this reply',exact:true});
  await choose();await expect(stop).toBeVisible();
  await expect.poll(()=>calls).toBe(2);
  await stop.click();release();
  await expect(stop).toHaveCount(0);
  await expect(page.getByText('A test screenshot.',{exact:true})).toHaveCount(0);
});
