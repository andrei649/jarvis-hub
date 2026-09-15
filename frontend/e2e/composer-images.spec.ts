import {expect,test} from '@playwright/test';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC';
const status={configured:true,model:'vision-test',backend:'custom',destination:'https://vision.example/v1',binding:'a'.repeat(64),local:false};
const result={ok:true,response:'A test screenshot.',model:status.model,backend:status.backend,destination:status.destination,local:false};
test('choose paste drop, explicit remote consent, vision provenance and unchanged text chat',async({page})=>{
  const images:any[]=[],texts:any[]=[];
  await page.route('**/api/vlm/composer/status',route=>route.fulfill({json:status}));
  await page.route('**/api/vlm/composer/describe',route=>{images.push(route.request().postDataJSON());return route.fulfill({json:result});});
  await page.route('**/chat/stream',route=>{texts.push(route.request().postDataJSON());return route.fulfill({contentType:'text/event-stream',body:'data: {"type":"start","agent":"jarvis"}\n\ndata: {"type":"end","agent":"jarvis","text":"Text remains text."}\n\n'});});
  await page.goto('/one/v2/chat?demo=1');
  await page.getByLabel('Attach images',{exact:true}).setInputFiles({name:'chosen.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
  await expect(page.getByAltText('chosen.png',{exact:true})).toBeVisible();
  for(const type of ['paste','drop'])await page.locator('.inputbar input').evaluate((element,{type,png})=>{
    const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],type+'.png',{type:'image/png'}));
    const event=type==='paste'?new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}):new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true});
    element.dispatchEvent(event);
  },{type,png});
  await expect(page.getByAltText('paste.png',{exact:true})).toBeVisible();await expect(page.getByAltText('drop.png',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Remove chosen.png'}).click();
  await expect(page.getByAltText('chosen.png',{exact:true})).toHaveCount(0);
  await page.locator('.inputbar input').fill('Describe screenshot');
  await expect(page.getByRole('button',{name:'TRANSMIT',exact:true})).toBeDisabled();expect(images).toHaveLength(0);
  await page.getByRole('checkbox',{name:/Send these images to https:\/\/vision.example/}).check();
  await page.getByRole('button',{name:'TRANSMIT',exact:true}).click();
  await expect(page.getByText('A test screenshot.',{exact:true})).toBeVisible();
  await expect(page.getByText('VISION ANALYSIS',{exact:true})).toBeVisible();
  await expect(page.getByText(/vision-test · custom · https:\/\/vision.example/)).toBeVisible();
  expect(images).toHaveLength(1);expect(images[0].images).toHaveLength(2);expect(images[0]).toMatchObject({prompt:'Describe screenshot',expected_destination:status.destination,remote_ack:true});
  expect(texts).toHaveLength(0);
  await page.locator('.inputbar input').fill('ordinary message');await page.getByRole('button',{name:'TRANSMIT',exact:true}).click();
  await expect(page.getByText('Text remains text.',{exact:true})).toBeVisible();
  expect(texts).toEqual([{message:'ordinary message',agent:'jarvis'}]);
});
test('stale destination fails visibly and a cancelled late vision result is ignored',async({page})=>{
  let calls=0,release:()=>void=()=>{};
  await page.route('**/api/vlm/composer/status',route=>route.fulfill({json:{...status,local:true}}));
  await page.route('**/api/vlm/composer/describe',async route=>{
    if(calls++===0)return route.fulfill({status:409,json:{error:'Vision destination changed; review it again'}});
    await new Promise<void>(resolve=>release=resolve);await route.fulfill({json:result}).catch(()=>{});
  });
  await page.goto('/v2/chat?demo=1');
  const choose=async()=>{await page.getByLabel('Attach images',{exact:true}).setInputFiles({name:'shot.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await page.getByRole('button',{name:'TRANSMIT',exact:true}).click();};
  await choose();await expect(page.getByText(/Vision analysis failed: Vision destination changed/)).toBeVisible();
  await choose();await expect(page.getByRole('button',{name:'Stop generating'})).toBeVisible();
  await expect.poll(()=>calls).toBe(2);
  await page.getByRole('button',{name:'Stop generating'}).click();release();
  await expect(page.getByRole('button',{name:'Stop generating'})).toHaveCount(0);
  await expect(page.getByText('A test screenshot.',{exact:true})).toHaveCount(0);
});
