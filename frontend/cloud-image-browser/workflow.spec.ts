import {expect,test} from '@playwright/test';
test('cloud approval roundtrip returns saved PNG and catalog export under prefix',async({page,request})=>{
  const initial=await (await request.get('/nerva/_test/state')).json();
  await page.addInitScript(()=>{localStorage.setItem('hud.user_token','cloud-hud-user');localStorage.setItem('hud.admin_token','cloud-hud-owner');});
  await page.goto('/nerva/v2/console/images?demo=1');
  await expect(page.getByLabel('Image provider')).toBeVisible();
  await page.getByLabel('Image provider').selectOption('cloud');
  await expect(page.getByText('Configured · connection untested.',{exact:true})).toBeVisible();
  await page.getByLabel('Image prompt').fill('blue square');
  const proposed=page.waitForResponse(r=>r.url().endsWith('/api/media/generate') && r.request().method()==='POST');
  await page.getByRole('button',{name:'Propose image',exact:true}).click();
  const response=await proposed;expect(response.status()).toBe(202);
  const {task_id}=await response.json();
  // the cloud proposal names its provider and model (api/images.ts proposeCloudImage sends the chosen options)
  expect(response.request().postDataJSON()).toEqual({kind:'image',cloud:true,backend:'openai',model:'gpt-image-1.5',prompt:'blue square',size:'1024x1024',quality:'low'});
  await page.getByRole('link',{name:'Open Decision Inbox'}).click();
  await expect(page.getByText('blue square',{exact:true})).toBeVisible();
  await expect(page.getByText(/OpenAI.*gpt-image-1.5.*potentially paid/)).toBeVisible();
  await expect(page.getByTitle('edit',{exact:true})).toHaveCount(0);
  const returnHref=await page.getByRole('link',{name:'Watch image task'}).getAttribute('href');
  expect(returnHref).toBe('/nerva/v2/console/images?image_task='+task_id);
  expect(await (await request.get('/nerva/_test/state')).json()).toEqual({requests:initial.requests,tasks:initial.tasks+1});
  // A cloud image request is queued at risk tier 3 (agents/core/cloud_image_runtime.py), so the
  // inbox's accept is a typed signature (PHASE_B_PLAN.md §5.4, §8.3: the docket's grading): the
  // phrase box opens, Confirm stays off until the phrase is typed exactly, and Enter never signs.
  const decisions:string[]=[];page.on('request',r=>{if(r.url().endsWith('/decision'))decisions.push(r.method());});
  await page.getByTitle('accept',{exact:true}).click();
  const phrase=page.getByRole('textbox',{name:/^type sign to accept /});
  const confirm=page.getByRole('button',{name:'confirm accept',exact:true});
  await expect(phrase).toBeFocused();await expect(phrase).toHaveAttribute('placeholder','sign');
  await expect(confirm).toBeDisabled();
  await phrase.fill('sig');await expect(confirm).toBeDisabled();
  await phrase.fill('sign');await expect(confirm).toBeEnabled();
  await phrase.press('Enter');await page.waitForTimeout(500);expect(decisions).toEqual([]);
  const decision=page.waitForResponse(r=>r.url().endsWith('/decision'));
  await confirm.click();expect((await decision).status()).toBe(200);
  expect(decisions).toEqual(['POST']);
  await page.getByRole('link',{name:'Watch decided image task'}).click();
  const artifact=await (await request.get('/nerva/api/media/generation-tasks/'+task_id,{headers:{'X-Admin-Token':'cloud-hud-owner'}})).json();
  expect(artifact).toMatchObject({state:'ready'});
  expect(await (await request.get('/nerva/_test/state')).json()).toEqual({requests:initial.requests+1,tasks:initial.tasks+1});
  await expect(page.getByRole('img',{name:'Generated image'})).toBeVisible();
  const unauthorized=await request.get('/nerva/api/media/generation-tasks/'+task_id);expect(unauthorized.status()).toBe(401);
  await page.getByRole('link',{name:'Open Media Gallery'}).click();
  const selected=page.getByLabel(/^Select md-/).first();await expect(selected).toBeVisible();await selected.check();
  const exported=page.waitForResponse(r=>r.url().endsWith('/api/media/export'));
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export selected media (1)'}).click();
  expect((await exported).status()).toBe(200);await download;
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
