import { test, expect } from '@playwright/test';
// Exercise real Django/PostgreSQL. Do not record traces containing credentials.
test.use({ trace:'off', screenshot:'off', video:'off' });

test('new business receives without shelves, sells, records rent, reconciles and locks across tabs', async ({page, context}) => {
  test.setTimeout(90000);
  const username=`retail-${Date.now()}`;
  const password='Browser-test-pass-9824';
  await page.goto('/register');
  await page.getByLabel('First name',{exact:true}).fill('Mama');
  await page.getByLabel('Last name',{exact:true}).fill('Shop');
  await page.getByLabel('Phone number',{exact:true}).fill('0712 345 678');
  await page.getByLabel('Email',{exact:true}).fill(`${username}@example.test`);
  await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByLabel('Confirm password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Create account and continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your business'})).toBeVisible();
  await page.getByLabel('Business name',{exact:true}).fill('Mama Shop');
  await page.getByLabel('Describe your business in your own words').fill('A duka selling phone accessories and household goods.');
  await page.getByRole('button',{name:'Continue'}).click();
  // What it does: the description ticks the usual tools; the test makes sure a shop's are on, whatever was suggested.
  await expect(page.getByRole('heading',{name:'What it does'})).toBeVisible();
  await page.getByLabel('What do you call your kind of business?').fill('Duka');
  const tick=async(name)=>{
    const card=page.getByRole('button',{name}).first();
    if (await card.getAttribute('aria-pressed')!=='true') await card.click();
  };
  await tick(/^Sell products I keep in stock/);
  await tick(/^Point of sale/);
  await page.getByRole('button',{name:'Continue'}).click();
  // A starter list may come next; then the plan. Reports, used below, come with the Pro plan.
  if (await page.getByRole('heading',{name:'Your starter list'}).isVisible().catch(()=>false)) await page.getByRole('button',{name:'Continue'}).click();
  await expect(page.getByRole('heading',{name:'Your plan'})).toBeVisible();
  await page.getByRole('button',{name:/^Pro · /}).click();
  await page.getByRole('button',{name:'Continue'}).click();
  // Location & money: the first branch name is filled in; one business, one drawer.
  await expect(page.getByRole('heading',{name:'Location & money'})).toBeVisible();
  const branch=page.getByLabel('First branch or shop name');
  if (!(await branch.inputValue())) await branch.fill('Main shop');
  await page.getByRole('button',{name:'Continue'}).click();
  await expect(page.getByRole('heading',{name:'Review'})).toBeVisible();
  await page.getByRole('button',{name:'Create business workspace'}).click();
  await page.getByRole('button',{name:'Skip for now'}).click();
  // Last set-up step: how customers pay. Manual payments are fine for this shop.
  await page.getByRole('button',{name:'Go to my dashboard'}).click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
  const variant=await page.evaluate(async()=>{
    const {api}=await import('/src/core/api/client.js');
    const category=await api('/api/v1/catalog/categories/',{method:'POST',body:JSON.stringify({name:'Mobile Accessories'})});
    const product=await api('/api/v1/catalog/products/',{method:'POST',body:JSON.stringify({name:'Test charger',slug:'test-charger',category:category.id,ecommerce_visible:false})});
    return api('/api/v1/catalog/variants/',{method:'POST',body:JSON.stringify({product:product.id,name:'Standard',sku:'CHARGER',selling_price:'1000'})});
  });
  expect(variant.id).toBeTruthy();
  await page.goto('/admin/quick-receive');
  await page.getByPlaceholder('Find item by name or barcode').fill('Test charger');
  await page.getByRole('listbox',{name:'Product suggestions'}).getByRole('option').first().click();
  await page.getByLabel('Quantity received').fill('1');
  await page.getByLabel('Buying price for one').fill('400');
  await page.getByLabel('Supplier',{exact:true}).fill('Charger supplier');
  // A first delivery is taken as bought with no supplier document (the page says so), so there is no invoice number to type.
  await page.getByRole('button',{name:'Receive stock',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:/Test charger.* added/})).toBeVisible();
  await page.goto('/admin/pos');
  await page.getByRole('button',{name:/^Test charger/}).first().click();
  // Complete sale opens the checkout. Charging sells nothing yet; the cash taken on the checkout completes the sale.
  await page.getByRole('button',{name:/^Complete sale/}).click();
  await page.getByRole('button',{name:/^Charge/}).click();
  await page.getByRole('button',{name:/^Take .* cash$/}).click();
  await expect(page.getByText(/Sale complete/)).toBeVisible();
  await page.goto('/admin/expenses');
  await page.getByLabel('What was it for?').fill('Rent');
  await page.getByLabel('Category',{exact:true}).fill('Rent');
  await page.getByLabel('Amount',{exact:true}).fill('200');
  await page.getByRole('button',{name:'Record expense',exact:true}).click();
  await expect(page.getByRole('row').filter({hasText:'Rent'}).filter({hasText:'200.00'}).first()).toBeVisible();
  await page.goto('/admin/reports');
  // Sold at 1000, bought at 400, rent 200.
  const card=(label)=>page.locator('.reportCard').filter({has:page.getByText(label,{exact:true})});
  await expect(card('Profit before running costs')).toContainText('600.00');
  await expect(card('Profit earned')).toContainText('400.00');
  const other=await context.newPage();
  await other.goto('/admin/reports');
  await expect(other.getByRole('heading',{name:'Where the business stands today'})).toBeVisible();
  await page.goto('/admin/expenses');
  await page.getByLabel('What was it for?').fill('Private unsaved transport');
  await page.getByRole('button',{name:'Lock workspace',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('Workspace locked');
  await expect(other.getByRole('dialog')).toContainText('Workspace locked');
  await expect(page.locator('.sessionWorkspace')).toHaveCSS('visibility','hidden');
  await page.getByLabel('Password',{exact:true}).fill(password);
  // A password filled in all at once (saved, autofilled or pasted) opens the workspace by itself.
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByLabel('What was it for?')).toHaveValue('Private unsaved transport');
  await expect(other.getByRole('dialog')).toHaveCount(0);
  const stored=await page.evaluate(()=>[...Object.values(localStorage),...Object.values(sessionStorage)]);
  expect(stored.some(value=>value.includes('access_token')||value.includes('lintech_refresh'))).toBe(false);
});
